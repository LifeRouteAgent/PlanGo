<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import AmapTripMap from "../components/AmapTripMap.vue";
import {
  adjustPlanPoi,
  executePlanStream,
  exportPlanCalendar,
  exportPlanPdf,
  getDataSourceStatus,
  getTrace,
  planTripStream,
  revisePlanStream
} from "../services/api";
import type {
  AgentThinkingEvent,
  DataSourceStatus,
  ExecutionStep,
  PlanAction,
  PoiItem,
  RankedPlan,
  RouteSegment,
  TimelineItem,
  TraceEvent,
  TraceProgressEvent,
  TraceResponse,
  TripPlanResponse
} from "../types";

const query = ref("周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算 200");
const loading = ref(false);
const errorMessage = ref("");
const result = ref<TripPlanResponse | null>(null);
const dataSource = ref<DataSourceStatus | null>(null);
const streamedResponse = ref("");
const streamStatus = ref("");
const hasResponseChunk = ref(false);
const selectedPlanIndex = ref(0);
const thinkingEvents = ref<AgentThinkingEvent[]>([]);
const traceEvents = ref<TraceProgressEvent[]>([]);
const traceDetail = ref<TraceResponse | null>(null);
const traceLoading = ref(false);
const adjustingPoiId = ref("");
const executionRunning = ref(false);
const executionStatus = ref("");
const executionSteps = ref<ExecutionStep[]>([]);
const sessionId = ref(getInitialSessionId());
const traceId = ref("");
const runId = ref("");
const activePanel = ref<"plans" | "profile">("plans");
const theme = ref<"light" | "dark">(getInitialTheme());
const isDarkTheme = computed(() => theme.value === "dark");

const productTraceEventNames = new Set([
  "intent_detected",
  "constraints_built",
  "skill_selected",
  "poi_collected",
  "skill_ranked",
  "route_candidate_built",
  "verification_issue",
  "plan_ranked"
]);

const quickQueries = [
  "你是什么模型",
  "周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远",
  "周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算 200",
  "推荐几个适合朋友聚会的餐厅",
  "周日下午带孩子玩半天，想室内活动加吃饭，预算 500"
];

const rankedPlans = computed(() => result.value?.ranked_plans ?? []);
const selectedPlan = computed(() => rankedPlans.value[selectedPlanIndex.value] ?? result.value?.selected_plan ?? null);
const hasPlan = computed(() => Boolean(selectedPlan.value?.id));
const placeCards = computed(() => buildPlaceCards(selectedPlan.value));
const currentIssues = computed(() => {
  const selectedIssues = selectedPlan.value?.issues ?? [];
  return selectedIssues.length ? selectedIssues : result.value?.errors ?? [];
});
const planActions = computed(() => selectedPlan.value?.plan_actions ?? []);
const planStatus = computed(() => {
  if (!result.value) return "待规划";
  if (result.value.need_clarification) return "需要补充信息";
  return result.value.execution_status === "simulated" ? "已生成" : result.value.execution_status;
});
const traceNodeEvents = computed(() => (traceDetail.value?.events ?? []).filter((event) => event.event_type === "node_run"));
const traceToolEvents = computed(() => (traceDetail.value?.events ?? []).filter((event) => event.event_type === "tool_call"));
const traceIssueEvents = computed(() =>
  (traceDetail.value?.events ?? []).filter((event) =>
    event.event_type === "product_progress" || event.event_type === "verification_issue"
  )
);
const failedToolCount = computed(() => traceToolEvents.value.filter((event) => event.success === false).length);
const fallbackToolCount = computed(() => traceToolEvents.value.filter((event) => event.source === "fallback" || Boolean(event.fallback)).length);

onMounted(async () => {
  applyTheme(theme.value);
  try {
    dataSource.value = await getDataSourceStatus();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "数据源状态请求失败";
  }
});

function getInitialTheme(): "light" | "dark" {
  const savedTheme = window.localStorage.getItem("liferoute-theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function toggleTheme() {
  theme.value = isDarkTheme.value ? "light" : "dark";
  window.localStorage.setItem("liferoute-theme", theme.value);
  applyTheme(theme.value);
}

function applyTheme(nextTheme: "light" | "dark") {
  document.documentElement.dataset.theme = nextTheme;
}

async function submitPlan() {
  errorMessage.value = "";
  loading.value = true;
  streamedResponse.value = "";
  streamStatus.value = "";
  hasResponseChunk.value = false;
  selectedPlanIndex.value = 0;
  thinkingEvents.value = [];
  traceEvents.value = [];
  traceDetail.value = null;
  adjustingPoiId.value = "";
  executionSteps.value = [];
  executionStatus.value = "";

  const shouldRevise = Boolean(result.value?.ranked_plans?.length) && looksLikeRevision(query.value);
  if (!shouldRevise) {
    result.value = null;
  }

  try {
    const finalResult = await (shouldRevise ? revisePlanStream : planTripStream)(
      shouldRevise
        ? {
            session_id: sessionId.value,
            user_query: query.value,
            selected_plan_id: selectedPlan.value?.id,
            max_replanning_count: 2
          }
        : {
            user_query: query.value,
            max_replanning_count: 2,
            session_id: sessionId.value
          },
      {
        onEvent: (event) => {
          if (event.event === "status" || event.event === "metadata" || event.event === "node_update" || event.event === "progress") {
            const message = event.data.message ?? event.data.stage ?? event.event;
            streamStatus.value = String(message);
          }
          if (productTraceEventNames.has(event.event)) {
            appendTraceEvent(event.event, event.data);
            const message = event.data.message ?? event.data.title ?? event.event;
            streamStatus.value = String(message);
          }
          if (event.event === "agent_thinking") {
            appendThinkingEvent(event.data as unknown as AgentThinkingEvent);
          }
        },
        onChunk: (delta) => {
          if (!hasResponseChunk.value) {
            streamedResponse.value = "";
            hasResponseChunk.value = true;
          }
          streamedResponse.value += delta;
        },
        onFinal: (response) => {
          result.value = response;
        }
      }
    );
    result.value = finalResult;
    if (finalResult.session_id) {
      sessionId.value = finalResult.session_id;
      window.localStorage.setItem("liferoute-session-id", finalResult.session_id);
    }
    traceId.value = finalResult.trace_id ?? traceId.value;
    runId.value = finalResult.run_id ?? runId.value;
    streamedResponse.value = finalResult.response_text;
    if (traceId.value) {
      await loadTraceDetail();
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "规划请求失败";
  } finally {
    loading.value = false;
    streamStatus.value = "";
  }
}

function useQuickQuery(text: string) {
  query.value = text;
}

function looksLikeRevision(text: string): boolean {
  return ["不要", "别", "太热", "下雨", "更近", "近一点", "更便宜", "省钱", "换", "室内", "时间短"].some((keyword) =>
    text.includes(keyword)
  );
}

function selectPlan(index: number) {
  selectedPlanIndex.value = index;
}

function appendThinkingEvent(event: AgentThinkingEvent) {
  if (!event?.agent || !event.message) return;
  thinkingEvents.value = [...thinkingEvents.value.slice(-11), event];
}

function getInitialSessionId(): string {
  const savedSession = window.localStorage.getItem("liferoute-session-id");
  if (savedSession) return savedSession;
  const nextSession = `web_${crypto.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`}`;
  window.localStorage.setItem("liferoute-session-id", nextSession);
  return nextSession;
}

function appendTraceEvent(eventName: string, payload: Record<string, unknown>) {
  const title = typeof payload.title === "string" ? payload.title : traceTitle(eventName);
  const message = typeof payload.message === "string" ? payload.message : "当前阶段已完成。";
  const stage = typeof payload.stage === "string" ? payload.stage : undefined;
  const details = Object.fromEntries(
    Object.entries(payload).filter(([key]) => !["title", "message", "stage"].includes(key))
  );
  const nextEvent: TraceProgressEvent = {
    event: eventName,
    stage,
    title,
    message,
    details
  };
  traceEvents.value = [...traceEvents.value.filter((item) => item.event !== eventName), nextEvent].slice(-8);
}

function traceTitle(eventName: string) {
  const titles: Record<string, string> = {
    intent_detected: "理解需求",
    constraints_built: "整理条件",
    skill_selected: "选择能力",
    poi_collected: "筛选地点",
    skill_ranked: "推荐排序",
    route_candidate_built: "生成动线",
    verification_issue: "校验方案",
    plan_ranked: "排序方案"
  };
  return titles[eventName] ?? "规划进度";
}

async function loadTraceDetail() {
  if (!traceId.value) return;
  traceLoading.value = true;
  try {
    traceDetail.value = await getTrace(traceId.value);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "Trace 读取失败";
  } finally {
    traceLoading.value = false;
  }
}

async function handlePlanAction(action: PlanAction) {
  if (!selectedPlan.value) return;
  if (action.type === "execute" || action.id === "execute_plan") {
    await executeSelectedPlan();
    return;
  }
  if (action.type === "export" || action.id === "share_pdf") {
    await sharePlanPdf();
    return;
  }
  if (action.type === "calendar" || action.id === "calendar_ics") {
    await sharePlanCalendar();
    return;
  }
  if (action.prompt) {
    query.value = `${query.value}\n调整要求：${action.prompt}`;
    await submitPlan();
  }
}

async function adjustPoi(card: PlaceCard, prompt: string) {
  if (!selectedPlan.value?.id) return;
  adjustingPoiId.value = card.id;
  errorMessage.value = "";
  try {
    const response = await adjustPlanPoi(selectedPlan.value, card.id, prompt);
    if (!response.success) {
      errorMessage.value = response.message;
      return;
    }
    applyAdjustedPlan(response.plan, response.message);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "局部调整失败";
  } finally {
    adjustingPoiId.value = "";
  }
}

function applyAdjustedPlan(plan: RankedPlan, message: string) {
  if (!result.value) return;
  const plans = [...(result.value.ranked_plans ?? [])];
  plans[selectedPlanIndex.value] = plan;
  result.value = {
    ...result.value,
    selected_plan: selectedPlanIndex.value === 0 ? plan : result.value.selected_plan,
    ranked_plans: plans
  };
  appendThinkingEvent({
    agent: "plan_adjust",
    title: "局部替换完成",
    message,
    summary: { poi_id: plan.id, selected_plan_index: selectedPlanIndex.value }
  });
}

async function executeSelectedPlan() {
  if (!selectedPlan.value) return;
  executionRunning.value = true;
  executionStatus.value = "开始模拟执行";
  executionSteps.value = [];
  try {
    await executePlanStream(selectedPlan.value, {
      onStart: (payload) => {
        executionStatus.value = String(payload.message ?? "执行开始");
      },
      onStep: (step) => {
        upsertExecutionStep(step);
      },
      onDone: (payload) => {
        executionStatus.value = String(payload.message ?? "模拟执行完成");
      }
    }, {
      session_id: sessionId.value,
      trace_id: traceId.value,
      run_id: runId.value
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "执行方案失败";
  } finally {
    executionRunning.value = false;
  }
}

async function sharePlanPdf() {
  if (!selectedPlan.value) return;
  try {
    const blob = await exportPlanPdf(selectedPlan.value, {
      session_id: sessionId.value,
      trace_id: traceId.value
    });
    downloadBlob(blob, "liferoute-plan.pdf");
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "导出 PDF 失败";
  }
}

async function sharePlanCalendar() {
  if (!selectedPlan.value) return;
  try {
    const blob = await exportPlanCalendar(selectedPlan.value, {
      session_id: sessionId.value,
      trace_id: traceId.value,
      run_id: runId.value
    });
    downloadBlob(blob, "liferoute-plan.ics");
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "导出日历失败";
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function upsertExecutionStep(step: ExecutionStep) {
  const index = executionSteps.value.findIndex((item) => item.id === step.id);
  if (index >= 0) executionSteps.value[index] = step;
  else executionSteps.value.push(step);
}

interface PlaceCard {
  id: string;
  order: number;
  name: string;
  rating?: number;
  reasonLines: string[];
  optionPrompts: string[];
  distanceText: string;
  transportText: string;
  durationText: string;
  address: string;
  tags: string[];
  images: string[];
}

function buildPlaceCards(plan: RankedPlan | null): PlaceCard[] {
  if (!plan?.items?.length) return [];
  return plan.items.map((item, index) => {
    const timeline = findTimelineForItem(plan.timeline ?? [], item, index);
    const segment = index > 0 ? plan.route_segments?.[index - 1] : undefined;
    return {
      id: item.id,
      order: index + 1,
      name: item.name,
      rating: typeof item.rating === "number" && item.rating > 0 ? item.rating : undefined,
      reasonLines: buildReasonLines(item),
      optionPrompts: item.option_prompts ?? [],
      distanceText: formatDistance(index, timeline, segment),
      transportText: formatTransport(index === 0 ? timeline?.transport_mode : segment?.transport_mode),
      durationText: formatTravelDuration(index, timeline, segment),
      address: item.address,
      tags: item.tags ?? [],
      images: extractImages(item)
    };
  });
}

function findTimelineForItem(timeline: TimelineItem[], item: PoiItem, index: number) {
  return timeline.find((entry) => entry.poi_id === item.id) ?? timeline[index];
}

function buildReasonLines(item: PoiItem) {
  const source = item.recommendation_reason || item.reason || `${item.subcategory || "本地生活"}：${item.tags?.slice(0, 2).join("、") || "适合当前行程"}`;
  const parts = source.split(/[。；;，,]/).map((part) => part.trim()).filter(Boolean);
  const lines = parts.length >= 2 ? parts.slice(0, 2) : [parts[0] || "匹配你的活动偏好", budgetLine(item)];
  return lines.slice(0, 2);
}

function budgetLine(item: PoiItem) {
  const labels: Record<string, string> = {
    good: "预算适配较好",
    tight: "预算略紧，适合控制消费",
    over_budget: "可能超过预算，建议确认价格",
    unknown: "价格信息待确认"
  };
  return labels[item.budget_fit ?? "unknown"] ?? "适合当前场景";
}

function formatDistance(index: number, timeline?: TimelineItem, segment?: RouteSegment) {
  if (index === 0) {
    const distance = timeline?.distance_from_previous_km;
    return typeof distance === "number" && distance > 0 ? `${distance.toFixed(2)} km` : "起点未指定";
  }
  const distance = segment?.distance_km ?? timeline?.distance_from_previous_km;
  return typeof distance === "number" ? `${distance.toFixed(2)} km` : "距离待补充";
}

function formatTravelDuration(index: number, timeline?: TimelineItem, segment?: RouteSegment) {
  if (index === 0) {
    const minutes = timeline?.travel_from_previous_minutes;
    return typeof minutes === "number" && minutes > 0 ? `${minutes} 分钟` : "耗时待确认";
  }
  const minutes = segment?.duration_minutes ?? timeline?.travel_from_previous_minutes;
  return typeof minutes === "number" ? `${minutes} 分钟` : "耗时待补充";
}

function formatTransport(mode?: string) {
  const labels: Record<string, string> = {
    start: "起点",
    walk: "步行",
    taxi: "打车",
    transit_or_taxi: "地铁/打车",
    cross_district_taxi: "跨区打车",
    forced_timeout: "超时模拟"
  };
  return labels[mode ?? ""] ?? mode ?? "交通待确认";
}

function extractImages(item: PoiItem) {
  const rawImages = [
    ...(item.image_urls ?? []),
    ...(item.photo_urls ?? []),
    ...(item.photos ?? []).map((photo) => (typeof photo === "string" ? photo : photo.url ?? ""))
  ].filter(Boolean);
  return rawImages.length ? rawImages : fallbackImages(item);
}

function fallbackImages(item: PoiItem) {
  const themes: Record<string, [string, string, string]> = {
    poi_restaurant: ["#fff7d6", "#9a5b00", "餐饮"],
    poi_entertainment: ["#e8f4ff", "#075985", "娱乐"],
    poi_activity: ["#e9f8ef", "#166534", "活动"],
    poi_attraction: ["#f1edff", "#6d28d9", "景点"],
    poi_shopping: ["#fff0f2", "#be123c", "购物"],
    poi_fitness: ["#e2fbf5", "#0f766e", "运动"],
    poi_beauty: ["#faedff", "#a21caf", "养生"]
  };
  const [background, foreground, labelText] = themes[item.category] ?? ["#edf2f7", "#334155", "本地"];
  return [0, 1, 2].map((offset) => {
    const label = escapeSvgText(offset === 0 ? item.name : labelText);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="${background}"/><rect x="36" y="36" width="568" height="288" rx="18" fill="white" fill-opacity=".7"/><text x="50%" y="49%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="${foreground}">${label}</text><text x="50%" y="63%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" fill="${foreground}" opacity=".68">LifeRoute</text></svg>`;
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
  });
}

function escapeSvgText(text: string) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function nodeLabel(event: TraceEvent) {
  return event.node_name ?? "未知节点";
}

function toolLabel(event: TraceEvent) {
  return event.tool ?? "未知工具";
}
</script>

<template>
  <main :class="['site', { 'theme-dark': isDarkTheme }]">
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="#" aria-label="LifeRoute 首页">
          <span class="brand-mark">L</span>
          <span>LifeRoute</span>
        </a>
        <nav class="nav-links" aria-label="主导航">
          <a href="#planner">周末规划</a>
          <a href="#plans">推荐方案</a>
          <a href="#map">路线地图</a>
          <a href="#profile">个人中心</a>
          <a href="#observability" @click="activePanel = 'profile'">观测面板</a>
        </nav>
        <div class="topbar-actions">
          <button class="top-action" type="button" @click="activePanel = activePanel === 'profile' ? 'plans' : 'profile'">
            <span>运行观测</span>
            <strong>{{ activePanel === "profile" ? "返回方案" : "查看 Trace" }}</strong>
          </button>
          <button
            class="theme-toggle"
            type="button"
            :aria-label="isDarkTheme ? '切换到日间模式' : '切换到夜间模式'"
            :title="isDarkTheme ? '日间模式' : '夜间模式'"
            @click="toggleTheme"
          >
            <svg v-if="isDarkTheme" aria-hidden="true" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
            </svg>
            <svg v-else aria-hidden="true" viewBox="0 0 24 24">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
            </svg>
          </button>
        </div>
      </div>
    </header>

    <section id="planner" class="hero-section">
      <div class="hero-shell">
        <div class="hero-copy-block">
          <p class="eyebrow">本地生活规划助手</p>
          <h1>一句话，把周末安排成可出发的路线</h1>
          <p class="hero-copy">说出人数、时间、预算和想玩的内容，LifeRoute 会组合餐厅、娱乐、活动、商圈与路线，并给出可调整、可执行、可分享的方案。</p>
          <div class="trust-row" aria-label="产品能力">
            <span>3 个候选方案</span>
            <span>地点可局部替换</span>
            <span>预约 / 购票 / 打车模拟执行</span>
            <span>{{ dataSource?.enabled ? "数据库已连接" : "可体验模式" }}</span>
          </div>
        </div>

        <form class="planner-card" @submit.prevent="submitPlan">
          <div class="planner-card-head">
            <span>今天想怎么安排？</span>
            <strong>{{ loading ? "正在规划" : "立即生成" }}</strong>
          </div>
          <label class="query-box">
            <span>自然语言需求</span>
            <textarea v-model="query" placeholder="例如：周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远" />
          </label>
          <div class="search-actions">
            <button class="primary-button" type="submit" :disabled="loading">{{ loading ? "规划中..." : "生成方案" }}</button>
            <p class="mini-status">{{ streamStatus || "支持简单问答、单类推荐、完整行程规划和中途修改需求。" }}</p>
          </div>
        </form>
      </div>

      <div class="quick-shell" aria-label="快捷输入">
        <button v-for="item in quickQueries" :key="item" type="button" @click="useQuickQuery(item)">{{ item }}</button>
      </div>
    </section>

    <main class="product-shell">
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

      <section v-if="traceEvents.length" class="progress-strip">
        <div class="progress-title">
          <span>系统正在思考</span>
          <strong>{{ streamStatus || "已完成关键节点" }}</strong>
        </div>
        <ol>
          <li v-for="event in traceEvents" :key="event.event" class="trace-step active">
            <span>{{ event.title }}</span>
            <p>{{ event.message }}</p>
          </li>
        </ol>
      </section>

      <section v-if="activePanel === 'profile'" id="observability" class="observability-panel">
        <div class="section-heading">
          <div>
            <span>运行观测</span>
            <h2>观测面板</h2>
          </div>
          <button class="secondary-button" type="button" :disabled="!traceId || traceLoading" @click="loadTraceDetail">
            {{ traceLoading ? "刷新中..." : "刷新 Trace" }}
          </button>
        </div>

        <div class="trace-meta-grid">
          <div><span>Session</span><strong>{{ sessionId }}</strong></div>
          <div><span>Trace</span><strong>{{ traceId || "暂无" }}</strong></div>
          <div><span>节点数</span><strong>{{ traceDetail?.summary.node_count ?? 0 }}</strong></div>
          <div><span>工具调用</span><strong>{{ traceDetail?.summary.tool_count ?? 0 }}</strong></div>
          <div><span>失败工具</span><strong>{{ failedToolCount }}</strong></div>
          <div><span>Fallback</span><strong>{{ fallbackToolCount }}</strong></div>
        </div>

        <div v-if="!traceDetail" class="empty-product-state compact">
          <div>
            <span>暂无 Trace</span>
            <h2>生成一次方案后，这里会展示完整运行链路</h2>
            <p>包括每个 LangGraph 节点耗时、LLM / 数据库 / 高德 / PDF / 执行 mock 的调用结果，以及 Verifier 发现的问题。</p>
          </div>
        </div>

        <div v-else class="trace-layout">
          <article class="trace-card">
            <div class="section-heading compact">
              <div><span>节点耗时</span><h2>LangGraph 执行链路</h2></div>
            </div>
            <ol class="trace-list">
              <li v-for="event in traceNodeEvents" :key="`${event.node_name}-${event.timestamp}`">
                <strong>{{ nodeLabel(event) }}</strong>
                <span>{{ event.duration_ms ?? 0 }} ms</span>
                <p v-if="event.error">{{ event.error }}</p>
              </li>
            </ol>
          </article>

          <article class="trace-card">
            <div class="section-heading compact">
              <div><span>工具调用</span><h2>外部能力与 fallback</h2></div>
            </div>
            <ol class="trace-list">
              <li v-for="event in traceToolEvents.slice(-18)" :key="`${event.tool}-${event.timestamp}`" :class="{ failed: event.success === false }">
                <strong>{{ toolLabel(event) }}</strong>
                <span>{{ event.success === false ? "失败" : "成功" }} / {{ event.source ?? "live" }}</span>
                <p v-if="event.error">{{ event.error }}</p>
              </li>
            </ol>
          </article>

          <article class="trace-card wide">
            <div class="section-heading compact">
              <div><span>QA / Verifier</span><h2>系统发现的问题</h2></div>
            </div>
            <ol class="trace-list">
              <li v-for="event in traceIssueEvents.slice(-10)" :key="`${event.event_type}-${event.timestamp}`">
                <strong>{{ event.event_type }}</strong>
                <span>{{ event.stage ?? "product" }}</span>
                <p>{{ event.message ?? event.title ?? "已记录观测事件" }}</p>
              </li>
            </ol>
          </article>
        </div>
      </section>

      <section v-if="!result && !loading && activePanel === 'plans'" class="empty-product-state">
        <div>
          <span>等待你的需求</span>
          <h2>先生成一个可执行周末方案</h2>
          <p>你也可以直接问“你是什么模型”“你能做什么”，系统会走问答链路，不会误触发行程规划。</p>
        </div>
        <div class="empty-demo-card">
          <strong>示例</strong>
          <p>周末上午和朋友打麻将再唱歌，预算 200</p>
          <span>会返回娱乐聚会方案、路线、预算、局部替换选项和执行按钮。</span>
        </div>
      </section>

      <section v-if="result && activePanel === 'plans'" id="plans" class="plan-layout">
        <article class="plan-main-card">
          <div class="section-heading">
            <div>
              <span>{{ result.is_revision ? "已按新需求调整" : "推荐方案" }}</span>
              <h2>{{ selectedPlan?.title ?? "方案已生成" }}</h2>
            </div>
            <strong>{{ planStatus }}</strong>
          </div>

          <div v-if="selectedPlan" class="plan-summary-grid">
            <div><span>总时长</span><strong>{{ selectedPlan.total_duration_minutes ?? 0 }} 分钟</strong></div>
            <div><span>路上时间</span><strong>{{ selectedPlan.route_minutes ?? 0 }} 分钟</strong></div>
            <div><span>预算估算</span><strong>{{ selectedPlan.estimated_budget ?? 0 }} 元</strong></div>
            <div><span>方案评分</span><strong>{{ selectedPlan.plan_score ?? "待评估" }}</strong></div>
          </div>

          <p v-if="selectedPlan?.recommendation_reason" class="plan-reason">{{ selectedPlan.recommendation_reason }}</p>
          <pre v-else-if="streamedResponse" class="response">{{ streamedResponse }}</pre>

          <div v-if="planActions.length" class="plan-action-row" aria-label="方案操作">
            <button v-for="action in planActions" :key="action.id" :class="['plan-action', 'plan-action-' + action.type]" :disabled="executionRunning && (action.type === 'execute' || action.id === 'execute_plan')" type="button" @click="handlePlanAction(action)">{{ action.label }}</button>
          </div>
        </article>

        <aside class="plan-side-card" aria-label="候选方案">
          <div class="section-heading compact">
            <div><span>更多选择</span><h2>3 个方案对比</h2></div>
          </div>
          <ol v-if="rankedPlans.length" class="candidate-list">
            <li v-for="(plan, index) in rankedPlans.slice(0, 3)" :key="plan.id" :class="['candidate-item', { selected: selectedPlanIndex === index }]">
              <button type="button" @click="selectPlan(index)">
                <span>方案 {{ index + 1 }}</span>
                <strong>{{ plan.title ?? plan.id }}</strong>
                <em>{{ plan.plan_score ?? "待评估" }} 分</em>
              </button>
              <p>{{ plan.recommendation_reason ?? "匹配当前需求的可执行备选方案。" }}</p>
              <div class="pros-cons">
                <div><b>优点</b><p v-for="item in (plan.pros ?? []).slice(0, 2)" :key="item">{{ item }}</p></div>
                <div><b>注意</b><p v-for="item in (plan.cons ?? []).slice(0, 2)" :key="item">{{ item }}</p></div>
              </div>
            </li>
          </ol>
        </aside>
      </section>

      <section v-if="placeCards.length && activePanel === 'plans'" class="experience-layout">
        <div class="experience-main">
          <div class="section-heading">
            <div><span>路线地点</span><h2>每一站为什么值得去</h2></div>
            <strong>{{ placeCards.length }} 站</strong>
          </div>

          <ol class="place-list">
            <li v-for="card in placeCards" :key="card.id" class="place-card">
              <div class="image-strip" :aria-label="`${card.name} 图片`">
                <img v-for="(image, imageIndex) in card.images" :key="card.id + '-' + imageIndex" :src="image" :alt="`${card.name} 图片 ${imageIndex + 1}`" loading="lazy" />
              </div>

              <div class="place-content">
                <div class="place-heading">
                  <span class="station-index">第 {{ card.order }} 站</span>
                  <strong>{{ card.name }}</strong>
                  <em v-if="card.rating">评分 {{ card.rating.toFixed(1) }}</em>
                </div>

                <div class="travel-line">
                  <span>{{ card.distanceText }}</span>
                  <span>{{ card.transportText }}</span>
                  <span>{{ card.durationText }}</span>
                </div>

                <p class="one-line-reason">{{ card.reasonLines[0] }}</p>
                <div v-if="card.reasonLines.length > 1" class="reason-group">
                  <p v-for="line in card.reasonLines.slice(1, 3)" :key="line">{{ line }}</p>
                </div>

                <p class="place-address">{{ card.address }}</p>

                <div v-if="card.tags.length" class="tag-row">
                  <span v-for="tag in card.tags.slice(0, 4)" :key="tag">{{ tag }}</span>
                </div>

                <div v-if="card.optionPrompts.length" class="option-row" aria-label="可选调整">
                  <button v-for="option in card.optionPrompts" :key="option" :disabled="adjustingPoiId === card.id" type="button" @click="adjustPoi(card, option)">{{ option }}</button>
                </div>
              </div>
            </li>
          </ol>
        </div>

        <aside id="map" class="sticky-side">
          <article class="map-card">
            <div class="section-heading compact">
              <div><span>路线地图</span><h2>看清动线</h2></div>
            </div>
            <AmapTripMap v-if="hasPlan && selectedPlan" :plan="selectedPlan" />
            <p v-else class="map-empty">生成方案后展示 POI 点位和路线连线。</p>
          </article>

          <article v-if="currentIssues.length" class="issue-panel">
            <div class="section-heading compact">
              <div><span>可执行提醒</span><h2>出发前留意</h2></div>
            </div>
            <ul>
              <li v-for="item in currentIssues" :key="item.code + '-' + item.source">
                <strong>{{ item.severity === "warning" ? "提醒" : "需要处理" }}</strong>
                <span>{{ item.message }}</span>
                <p>{{ item.suggestion }}</p>
              </li>
            </ul>
          </article>
        </aside>
      </section>

      <section id="execute" v-if="executionSteps.length || executionRunning || executionStatus" class="execution-panel">
        <div class="section-heading compact">
          <div><span>执行服务</span><h2>订座、购票、打车模拟进度</h2></div>
          <strong>{{ executionRunning ? "执行中" : "已完成" }}</strong>
        </div>
        <p v-if="executionStatus" class="execution-status">{{ executionStatus }}</p>
        <ol>
          <li v-for="step in executionSteps" :key="step.id" :class="'step-' + step.status">
            <span>{{ step.status === "running" ? "执行中" : "已完成" }}</span>
            <strong>{{ step.title }}</strong>
            <p>{{ step.result || step.description }}</p>
          </li>
        </ol>
      </section>
    </main>
  </main>
</template>

<style scoped>
.site { min-height: 100vh; background: #fff8f1; color: #211914; }
.topbar { position: sticky; z-index: 20; top: 0; border-bottom: 1px solid rgb(33 25 20 / 8%); background: rgb(255 255 255 / 92%); backdrop-filter: blur(14px); }
.topbar-inner, .hero-shell, .quick-shell, .product-shell { max-width: 1240px; margin: 0 auto; padding-right: 24px; padding-left: 24px; }
.topbar-inner { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 66px; }
.brand, .nav-links a { color: #211914; text-decoration: none; }
.brand { display: inline-flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 900; }
.brand-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 8px; background: #ff6b35; color: #fff; box-shadow: 0 10px 24px rgb(255 107 53 / 28%); }
.nav-links { display: flex; align-items: center; gap: 28px; font-size: 14px; font-weight: 700; }
.nav-links a { opacity: 0.72; }
.nav-links a:hover { opacity: 1; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.top-action { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 14px; border: 1px solid #ffe0cb; border-radius: 8px; background: #fff4ec; color: #8f3a16; font-size: 13px; cursor: pointer; }
.top-action strong { color: #e9571f; }
.theme-toggle { display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid #ecd9cb; border-radius: 8px; background: #fff; color: #6b3c24; cursor: pointer; }
.theme-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentcolor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.hero-section { padding: 48px 0 34px; background: #ffefe2; }
.hero-shell { display: grid; grid-template-columns: minmax(0, 1fr) 460px; gap: 36px; align-items: center; }
.eyebrow { margin: 0 0 12px; color: #da5019; font-size: 14px; font-weight: 900; }
.hero-copy-block h1 { margin: 0; max-width: 680px; font-size: clamp(40px, 6vw, 70px); line-height: 1.02; letter-spacing: 0; }
.hero-copy { max-width: 600px; margin: 22px 0 0; color: #6e5c51; font-size: 18px; line-height: 1.8; }
.trust-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
.trust-row span { min-height: 36px; padding: 8px 12px; border: 1px solid rgb(255 107 53 / 18%); border-radius: 8px; background: rgb(255 255 255 / 76%); color: #6b3c24; font-size: 13px; font-weight: 800; }
.planner-card, .progress-strip, .empty-product-state, .plan-main-card, .plan-side-card, .map-card, .issue-panel, .execution-panel, .observability-panel, .trace-card { border: 1px solid rgb(33 25 20 / 8%); border-radius: 8px; background: #fff; box-shadow: 0 16px 46px rgb(82 45 26 / 8%); }
.planner-card-head, .section-heading, .progress-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.planner-card-head { min-height: 58px; padding: 0 18px; border-bottom: 1px solid #f1e2d7; }
.planner-card-head span, .section-heading span, .progress-title span { color: #d75017; font-size: 12px; font-weight: 900; }
.query-box { display: grid; gap: 10px; padding: 18px; }
.query-box span { color: #4d4038; font-size: 14px; font-weight: 800; }
.query-box textarea { width: 100%; min-height: 146px; resize: vertical; border: 1px solid #ead7c8; border-radius: 8px; padding: 16px; background: #fffaf6; color: #241a14; font: inherit; line-height: 1.7; outline: none; }
.query-box textarea:focus { border-color: #ff8a50; box-shadow: 0 0 0 4px rgb(255 138 80 / 16%); }
.search-actions { display: flex; align-items: center; gap: 12px; padding: 0 18px 18px; }
.primary-button, .secondary-button, .plan-action, .option-row button, .quick-shell button, .candidate-item button { min-height: 44px; border: 0; border-radius: 8px; font: inherit; font-weight: 850; cursor: pointer; }
.primary-button { padding: 0 24px; background: #ff6b35; color: #fff; box-shadow: 0 14px 28px rgb(255 107 53 / 24%); }
.secondary-button { padding: 0 16px; border: 1px solid #ffd7c1; background: #fff5ed; color: #9e3b13; }
.primary-button:disabled, .secondary-button:disabled, .plan-action:disabled, .option-row button:disabled { cursor: not-allowed; opacity: 0.58; box-shadow: none; }
.mini-status, .stream-status { color: #7d6c62; font-size: 13px; line-height: 1.45; }
.quick-shell { display: flex; gap: 10px; overflow-x: auto; padding-top: 22px; padding-bottom: 4px; scrollbar-width: none; }
.quick-shell button { flex: 0 0 auto; max-width: 330px; padding: 0 14px; overflow: hidden; border: 1px solid #ffd9c2; background: #fff; color: #6f3e27; text-overflow: ellipsis; white-space: nowrap; }
.product-shell { padding-top: 30px; padding-bottom: 72px; }
.error { margin: 0 0 18px; padding: 14px 16px; border: 1px solid #ffd1c8; border-radius: 8px; background: #fff1ee; color: #b22c1f; font-weight: 800; }
.progress-strip, .observability-panel, .empty-product-state, .plan-main-card, .plan-side-card, .map-card, .issue-panel, .execution-panel { padding: 20px; }
.progress-strip { margin-bottom: 18px; }
.progress-strip ol { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 14px 0 0; padding: 0; list-style: none; }
.progress-strip li { min-height: 76px; padding: 12px; border: 1px solid #ffe1cd; border-radius: 8px; background: #fffaf6; }
.progress-strip li span { display: block; margin-bottom: 6px; color: #d75017; font-size: 12px; font-weight: 900; }
.progress-strip li p { margin: 0; color: #65564d; font-size: 13px; line-height: 1.6; }
.empty-product-state { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: center; }
.empty-product-state.compact { display: block; }
.empty-product-state span { color: #d75017; font-size: 13px; font-weight: 900; }
.empty-product-state h2 { margin: 8px 0; font-size: 28px; letter-spacing: 0; }
.empty-product-state p { margin: 0; color: #74665d; line-height: 1.7; }
.empty-demo-card { padding: 18px; border-radius: 8px; background: #21362f; color: #fff; }
.empty-demo-card p { margin: 14px 0; font-size: 22px; font-weight: 900; }
.plan-layout, .experience-layout, .trace-layout { display: grid; gap: 18px; align-items: start; }
.plan-layout { grid-template-columns: minmax(0, 1fr) 390px; }
.experience-layout { grid-template-columns: minmax(0, 1fr) 430px; margin-top: 18px; }
.trace-layout { grid-template-columns: 1fr 1fr; }
.trace-card.wide { grid-column: 1 / -1; }
.section-heading { margin-bottom: 16px; }
.section-heading.compact { margin-bottom: 12px; }
.section-heading h2 { margin: 4px 0 0; color: #211914; font-size: 22px; letter-spacing: 0; }
.section-heading strong { min-height: 32px; padding: 7px 10px; border-radius: 8px; background: #f1fbf7; color: #16806a; font-size: 13px; }
.plan-summary-grid, .trace-meta-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.trace-meta-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.plan-summary-grid div, .trace-meta-grid div { min-height: 82px; padding: 14px; border-radius: 8px; background: #fff7f0; overflow: hidden; }
.plan-summary-grid span, .trace-meta-grid span { display: block; color: #836b5e; font-size: 12px; font-weight: 800; }
.plan-summary-grid strong, .trace-meta-grid strong { display: block; margin-top: 8px; color: #211914; font-size: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-reason, .response, .soft-note { margin: 0; color: #66584f; line-height: 1.8; }
.response { max-height: 260px; overflow: auto; padding: 14px; border-radius: 8px; background: #fff8f1; white-space: pre-wrap; }
.plan-action-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.plan-action { padding: 0 16px; border: 1px solid #ffd7c1; background: #fff5ed; color: #9e3b13; }
.plan-action-execute { border-color: #ff6b35; background: #ff6b35; color: #fff; }
.plan-action-export { border-color: #cbe9df; background: #effbf7; color: #16735f; }
.candidate-list, .place-list, .execution-panel ol, .issue-panel ul, .trace-list { margin: 0; padding: 0; list-style: none; }
.candidate-list, .trace-list { display: grid; gap: 12px; }
.candidate-item, .trace-list li { border: 1px solid #f0ded0; border-radius: 8px; padding: 12px; background: #fffaf6; }
.trace-list li.failed { border-color: #ffb8aa; background: #fff0ed; }
.candidate-item.selected { border-color: #ff8a50; box-shadow: 0 0 0 4px rgb(255 138 80 / 12%); }
.candidate-item button { display: grid; width: 100%; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 0; background: transparent; color: #211914; text-align: left; }
.candidate-item button span, .candidate-item button em, .trace-list li span { color: #d75017; font-size: 12px; font-style: normal; font-weight: 900; }
.candidate-item > p, .trace-list p { margin: 10px 0 0; color: #6f6259; font-size: 13px; line-height: 1.6; }
.pros-cons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pros-cons div { min-height: 92px; padding: 10px; border-radius: 8px; background: #fff; }
.pros-cons p { margin: 6px 0 0; color: #74675e; font-size: 12px; line-height: 1.55; }
.place-list { display: grid; gap: 14px; }
.place-card { display: grid; grid-template-columns: 238px minmax(0, 1fr); gap: 16px; border: 1px solid rgb(33 25 20 / 8%); border-radius: 8px; padding: 12px; background: #fff; box-shadow: 0 14px 36px rgb(82 45 26 / 7%); }
.image-strip { display: flex; gap: 8px; min-width: 0; height: 178px; overflow-x: auto; border-radius: 8px; background: #f6eadf; scroll-snap-type: x mandatory; }
.image-strip img { flex: 0 0 100%; width: 100%; height: 178px; object-fit: cover; scroll-snap-align: start; }
.place-content { display: grid; align-content: start; gap: 10px; min-width: 0; }
.place-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.station-index { min-height: 28px; padding: 6px 9px; border-radius: 8px; background: #fff1e6; color: #d75017; font-size: 12px; font-weight: 900; }
.place-heading strong { overflow: hidden; color: #211914; font-size: 21px; text-overflow: ellipsis; white-space: nowrap; }
.place-heading em { color: #16806a; font-size: 13px; font-style: normal; font-weight: 900; }
.travel-line, .tag-row, .option-row { display: flex; flex-wrap: wrap; gap: 8px; }
.travel-line span, .tag-row span { min-height: 28px; padding: 6px 9px; border-radius: 8px; background: #f5f0ea; color: #65574e; font-size: 12px; font-weight: 800; }
.one-line-reason { margin: 0; color: #2f241d; font-weight: 900; line-height: 1.6; }
.reason-group p, .place-address { margin: 0; color: #786b62; font-size: 13px; line-height: 1.65; }
.option-row button { padding: 0 12px; border: 1px solid #d6ece4; background: #f2fffb; color: #16735f; font-size: 13px; }
.sticky-side { position: sticky; top: 86px; display: grid; gap: 14px; }
.map-card { min-height: 460px; }
.map-empty { margin: 0; padding: 18px; border-radius: 8px; background: #fff8f1; color: #74665d; line-height: 1.7; }
.issue-panel ul, .execution-panel ol { display: grid; gap: 10px; }
.issue-panel li, .execution-panel li { padding: 12px; border-radius: 8px; background: #fff8f1; }
.issue-panel li strong, .execution-panel li span { display: inline-flex; min-height: 24px; align-items: center; margin-right: 8px; color: #d75017; font-size: 12px; font-weight: 900; }
.issue-panel li span, .execution-panel li strong { color: #211914; font-weight: 900; }
.issue-panel li p, .execution-panel li p, .execution-status { margin: 8px 0 0; color: #76685f; line-height: 1.65; }
.execution-panel { margin-top: 18px; }
.step-completed, .step-done { background: #f0fbf6 !important; }
.step-running { background: #fff7e9 !important; }
.theme-dark { background: #0f141b; color: #edf1f7; }
.theme-dark .topbar { border-bottom-color: rgb(255 255 255 / 10%); background: rgb(15 20 27 / 90%); }
.theme-dark .brand, .theme-dark .nav-links a, .theme-dark .section-heading h2, .theme-dark .plan-summary-grid strong, .theme-dark .trace-meta-grid strong, .theme-dark .candidate-item button, .theme-dark .place-heading strong, .theme-dark .one-line-reason, .theme-dark .trace-list strong { color: #edf1f7; }
.theme-dark .hero-section { background: #18212b; }
.theme-dark .planner-card, .theme-dark .progress-strip, .theme-dark .empty-product-state, .theme-dark .plan-main-card, .theme-dark .plan-side-card, .theme-dark .map-card, .theme-dark .issue-panel, .theme-dark .execution-panel, .theme-dark .observability-panel, .theme-dark .trace-card, .theme-dark .place-card { border-color: rgb(255 255 255 / 10%); background: #141c26; box-shadow: 0 18px 48px rgb(0 0 0 / 26%); }
.theme-dark .query-box textarea, .theme-dark .response { border-color: #3b4655; background: #0f141b; color: #edf1f7; }
.theme-dark .plan-summary-grid div, .theme-dark .trace-meta-grid div, .theme-dark .candidate-item, .theme-dark .trace-list li, .theme-dark .pros-cons div, .theme-dark .travel-line span, .theme-dark .tag-row span, .theme-dark .map-empty, .theme-dark .issue-panel li, .theme-dark .step-running { background: #1b2632 !important; }
@media (max-width: 1080px) { .hero-shell, .plan-layout, .experience-layout, .trace-layout { grid-template-columns: 1fr; } .sticky-side { position: static; } .plan-side-card { order: -1; } .trace-card.wide { grid-column: auto; } }
@media (max-width: 760px) { .topbar-inner, .hero-shell, .quick-shell, .product-shell { padding-right: 16px; padding-left: 16px; } .nav-links { display: none; } .topbar-inner { gap: 12px; } .hero-section { padding-top: 30px; } .hero-copy-block h1 { font-size: 40px; } .hero-copy { font-size: 16px; } .search-actions, .plan-action-row { align-items: stretch; flex-direction: column; } .primary-button, .plan-action { width: 100%; } .empty-product-state, .place-card { grid-template-columns: 1fr; } .plan-summary-grid, .trace-meta-grid { grid-template-columns: 1fr 1fr; } .place-heading { grid-template-columns: 1fr; } .place-heading strong { white-space: normal; } .candidate-item button { grid-template-columns: 1fr; } }
</style>
