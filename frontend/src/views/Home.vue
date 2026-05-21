<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import AmapTripMap from "../components/AmapTripMap.vue";
import { adjustPlanPoi, executePlanStream, exportPlanPdf, getDataSourceStatus, planTripStream } from "../services/api";
import type { AgentThinkingEvent, DataSourceStatus, ExecutionStep, PlanAction, PoiItem, RankedPlan, RouteSegment, TimelineItem, TripPlanResponse } from "../types";

// 默认输入要像真实用户需求，方便演示时打开页面就能一键生成方案。
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
const adjustingPoiId = ref("");
const executionRunning = ref(false);
const executionStatus = ref("");
const executionSteps = ref<ExecutionStep[]>([]);
const theme = ref<"light" | "dark">(getInitialTheme());
const isDarkTheme = computed(() => theme.value === "dark");

const quickQueries = [
  "周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远",
  "周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算 200",
  "推荐几个适合朋友聚会的餐厅",
  "周日下午带孩子玩半天，想室内活动加吃饭，预算 500"
];

// 用户可以在 3 个候选方案之间切换，地图、地点卡片、优缺点都会跟随切换。
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
  adjustingPoiId.value = "";
  executionSteps.value = [];
  executionStatus.value = "";
  result.value = null;

  try {
    const finalResult = await planTripStream(
      { user_query: query.value, max_replanning_count: 2 },
      {
        onEvent: (event) => {
          if (event.event === "status" || event.event === "metadata" || event.event === "node_update" || event.event === "progress") {
            const message = event.data.message ?? event.data.stage ?? event.event;
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
    streamedResponse.value = finalResult.response_text;
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

function selectPlan(index: number) {
  selectedPlanIndex.value = index;
}

function appendThinkingEvent(event: AgentThinkingEvent) {
  if (!event?.agent || !event.message) return;
  thinkingEvents.value = [...thinkingEvents.value.slice(-11), event];
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
  if (action.prompt) {
    query.value = query.value + "\n调整要求：" + action.prompt;
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
    const blob = await exportPlanPdf(selectedPlan.value);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "liferoute-plan.pdf";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "导出 PDF 失败";
  }
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
  const source = item.recommendation_reason || item.reason || (item.subcategory || "本地生活") + "，" + (item.tags?.slice(0, 2).join("、") || "适合当前行程");
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
    return typeof distance === "number" && distance > 0 ? distance.toFixed(2) + " km" : "起点未指定";
  }
  const distance = segment?.distance_km ?? timeline?.distance_from_previous_km;
  return typeof distance === "number" ? distance.toFixed(2) + " km" : "距离待补充";
}

function formatTravelDuration(index: number, timeline?: TimelineItem, segment?: RouteSegment) {
  if (index === 0) {
    const minutes = timeline?.travel_from_previous_minutes;
    return typeof minutes === "number" && minutes > 0 ? minutes + " 分钟" : "耗时待确认";
  }
  const minutes = segment?.duration_minutes ?? timeline?.travel_from_previous_minutes;
  return typeof minutes === "number" ? minutes + " 分钟" : "耗时待补充";
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
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="' + background + '"/><rect x="36" y="36" width="568" height="288" rx="18" fill="white" fill-opacity=".7"/><text x="50%" y="49%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="' + foreground + '">' + label + '</text><text x="50%" y="63%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="17" fill="' + foreground + '" opacity=".68">LifeRoute</text></svg>';
    return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
  });
}

function escapeSvgText(text: string) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
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
          <a href="#execute">执行服务</a>
        </nav>
        <div class="topbar-actions">
          <div class="top-action">
            <span>本地精选</span>
            <strong>{{ dataSource?.enabled ? "已连接" : "可体验" }}</strong>
          </div>
          <button
            class="theme-toggle"
            type="button"
            :aria-label="isDarkTheme ? '切换到日间模式' : '切换到黑夜模式'"
            :title="isDarkTheme ? '日间模式' : '黑夜模式'"
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
            <span>地点可替换</span>
            <span>订座购票打车模拟执行</span>
          </div>
        </div>

        <form class="planner-card" @submit.prevent="submitPlan">
          <div class="planner-card-head">
            <span>今天想怎么安排？</span>
            <strong>{{ loading ? "正在规划" : "立即生成" }}</strong>
          </div>
          <label class="query-box">
            <span>输入你的需求</span>
            <textarea v-model="query" rows="5" placeholder="例如：周末上午和朋友出去玩 4 个小时，想打麻将打牌然后唱歌，预算 200" />
          </label>
          <div class="search-actions">
            <button class="primary-button" :disabled="loading || !query.trim()" type="submit">{{ loading ? "生成中..." : "生成周末方案" }}</button>
            <span v-if="streamStatus" class="stream-status">{{ streamStatus }}</span>
            <span v-else class="mini-status">{{ planStatus }}</span>
          </div>
        </form>
      </div>

      <div class="quick-shell" aria-label="快捷需求">
        <button v-for="item in quickQueries" :key="item" type="button" @click="useQuickQuery(item)">{{ item }}</button>
      </div>
    </section>

    <section class="product-shell">
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

      <section v-if="thinkingEvents.length || loading" class="progress-strip" aria-label="规划进度">
        <div class="progress-title">
          <span>规划进度</span>
          <strong>{{ loading ? "小助手正在处理" : "规划完成" }}</strong>
        </div>
        <ol>
          <li v-for="event in thinkingEvents" :key="event.agent + '-' + event.message">
            <span>{{ event.title ?? event.agent }}</span>
            <p>{{ event.message }}</p>
          </li>
          <li v-if="loading">
            <span>继续生成</span>
            <p>{{ streamStatus || "正在组合路线、校验时长和预算" }}</p>
          </li>
        </ol>
      </section>

      <section v-if="!hasPlan && !streamedResponse" class="empty-product-state">
        <div>
          <span>从自然语言开始</span>
          <h2>不用自己筛店、算路程、看营业时间</h2>
          <p>输入一句需求后，这里会展示 3 个方案、地图路线、地点卡片和后续执行动作。</p>
        </div>
        <div class="empty-demo-card">
          <strong>示例路线</strong>
          <p>棋牌室 → KTV → 夜宵</p>
          <span>低移动成本，适合朋友聚会</span>
        </div>
      </section>

      <section id="plans" v-if="hasPlan || streamedResponse" class="plan-layout">
        <article class="plan-main-card">
          <div class="section-heading">
            <div>
              <span>推荐给你</span>
              <h2>{{ selectedPlan?.title ?? "本地生活方案" }}</h2>
            </div>
            <strong>{{ result?.need_clarification ? "需要补充信息" : "可执行方案" }}</strong>
          </div>

          <div v-if="selectedPlan?.id" class="plan-summary-grid" aria-label="方案摘要">
            <div><span>预计时长</span><strong>{{ selectedPlan.total_duration_minutes ?? 0 }} 分钟</strong></div>
            <div><span>预计预算</span><strong>{{ selectedPlan.estimated_budget ?? 0 }} 元</strong></div>
            <div><span>交通时间</span><strong>{{ selectedPlan.route_minutes ?? 0 }} 分钟</strong></div>
            <div><span>推荐分</span><strong>{{ selectedPlan.plan_score ?? "待评估" }}</strong></div>
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
          <p v-else class="soft-note">方案生成后会在这里展示不同路线的取舍。</p>
        </aside>
      </section>

      <section v-if="placeCards.length" class="experience-layout">
        <div class="experience-main">
          <div class="section-heading">
            <div><span>路线地点</span><h2>每一站为什么值得去</h2></div>
            <strong>{{ placeCards.length }} 站</strong>
          </div>

          <ol class="place-list">
            <li v-for="card in placeCards" :key="card.id" class="place-card">
              <div class="image-strip" :aria-label="card.name + ' 图片'">
                <img v-for="(image, imageIndex) in card.images" :key="card.id + '-' + imageIndex" :src="image" :alt="card.name + ' 图片 ' + (imageIndex + 1)" loading="lazy" />
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
    </section>
  </main>
</template>

<style scoped>
/* 页面定位：这是给用户看的本地生活产品页面，不再展示 DAG、数据库表、原始日志等工程视角信息。 */
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
.topbar-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.top-action { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 14px; border: 1px solid #ffe0cb; border-radius: 8px; background: #fff4ec; color: #8f3a16; font-size: 13px; }
.top-action strong { color: #e9571f; }
.theme-toggle { display: grid; width: 40px; height: 40px; flex: 0 0 auto; place-items: center; border: 1px solid #ecd9cb; border-radius: 8px; background: #fff; color: #6b3c24; cursor: pointer; }
.theme-toggle:hover { border-color: #ff8a50; color: #d75017; }
.theme-toggle:focus-visible { outline: 4px solid rgb(255 138 80 / 18%); outline-offset: 1px; }
.theme-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentcolor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.hero-section { padding: 48px 0 34px; background: #ffefe2; }
.hero-shell { display: grid; grid-template-columns: minmax(0, 1fr) 460px; gap: 36px; align-items: center; }
.hero-copy-block { max-width: 690px; }
.eyebrow { margin: 0 0 12px; color: #da5019; font-size: 14px; font-weight: 900; }
.hero-copy-block h1 { margin: 0; max-width: 680px; font-size: clamp(40px, 6vw, 70px); line-height: 1.02; letter-spacing: 0; }
.hero-copy { max-width: 600px; margin: 22px 0 0; color: #6e5c51; font-size: 18px; line-height: 1.8; }
.trust-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
.trust-row span { min-height: 36px; padding: 8px 12px; border: 1px solid rgb(255 107 53 / 18%); border-radius: 8px; background: rgb(255 255 255 / 76%); color: #6b3c24; font-size: 13px; font-weight: 800; }
.planner-card { border: 1px solid rgb(33 25 20 / 8%); border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgb(101 50 22 / 18%); }
.planner-card-head, .section-heading, .progress-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.planner-card-head { min-height: 58px; padding: 0 18px; border-bottom: 1px solid #f1e2d7; }
.planner-card-head span, .section-heading span, .progress-title span { color: #d75017; font-size: 12px; font-weight: 900; }
.planner-card-head strong { color: #2f241d; font-size: 14px; }
.query-box { display: grid; gap: 10px; padding: 18px; }
.query-box span { color: #4d4038; font-size: 14px; font-weight: 800; }
.query-box textarea { width: 100%; min-height: 146px; resize: vertical; border: 1px solid #ead7c8; border-radius: 8px; padding: 16px; background: #fffaf6; color: #241a14; font: inherit; line-height: 1.7; outline: none; }
.query-box textarea:focus { border-color: #ff8a50; box-shadow: 0 0 0 4px rgb(255 138 80 / 16%); }
.search-actions { display: flex; align-items: center; gap: 12px; padding: 0 18px 18px; }
.primary-button, .plan-action, .option-row button, .quick-shell button, .candidate-item button { min-height: 44px; border: 0; border-radius: 8px; font: inherit; font-weight: 850; cursor: pointer; }
.primary-button { flex: 0 0 auto; padding: 0 24px; background: #ff6b35; color: #fff; box-shadow: 0 14px 28px rgb(255 107 53 / 24%); }
.primary-button:disabled, .plan-action:disabled, .option-row button:disabled { cursor: not-allowed; opacity: 0.58; box-shadow: none; }
.mini-status, .stream-status { color: #7d6c62; font-size: 13px; line-height: 1.45; }
.stream-status { color: #18876e; font-weight: 800; }
.quick-shell { display: flex; gap: 10px; overflow-x: auto; padding-top: 22px; padding-bottom: 4px; scrollbar-width: none; }
.quick-shell::-webkit-scrollbar { display: none; }
.quick-shell button { flex: 0 0 auto; max-width: 330px; padding: 0 14px; overflow: hidden; border: 1px solid #ffd9c2; background: #fff; color: #6f3e27; text-overflow: ellipsis; white-space: nowrap; }
.product-shell { padding-top: 30px; padding-bottom: 72px; }
.error { margin: 0 0 18px; padding: 14px 16px; border: 1px solid #ffd1c8; border-radius: 8px; background: #fff1ee; color: #b22c1f; font-weight: 800; }
.progress-strip, .empty-product-state, .plan-main-card, .plan-side-card, .map-card, .issue-panel, .execution-panel { border: 1px solid rgb(33 25 20 / 8%); border-radius: 8px; background: #fff; box-shadow: 0 16px 46px rgb(82 45 26 / 8%); }
.progress-strip { margin-bottom: 18px; padding: 16px; }
.progress-strip ol { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 14px 0 0; padding: 0; list-style: none; }
.progress-strip li { min-height: 76px; padding: 12px; border-radius: 8px; background: #fff8f2; }
.progress-strip li span { display: block; margin-bottom: 6px; color: #d75017; font-size: 12px; font-weight: 900; }
.progress-strip li p { margin: 0; color: #65564d; font-size: 13px; line-height: 1.6; }
.empty-product-state { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; align-items: center; padding: 28px; }
.empty-product-state span { color: #d75017; font-size: 13px; font-weight: 900; }
.empty-product-state h2 { margin: 8px 0; font-size: 28px; letter-spacing: 0; }
.empty-product-state p { margin: 0; color: #74665d; line-height: 1.7; }
.empty-demo-card { padding: 18px; border-radius: 8px; background: #21362f; color: #fff; }
.empty-demo-card strong, .empty-demo-card p, .empty-demo-card span { color: #fff; }
.empty-demo-card p { margin: 14px 0; font-size: 22px; font-weight: 900; }
.plan-layout, .experience-layout { display: grid; gap: 18px; align-items: start; }
.plan-layout { grid-template-columns: minmax(0, 1fr) 390px; }
.experience-layout { grid-template-columns: minmax(0, 1fr) 430px; margin-top: 18px; }
.plan-main-card, .plan-side-card, .map-card, .issue-panel, .execution-panel { padding: 20px; }
.section-heading { margin-bottom: 16px; }
.section-heading.compact { margin-bottom: 12px; }
.section-heading h2 { margin: 4px 0 0; color: #211914; font-size: 22px; letter-spacing: 0; }
.section-heading strong { min-height: 32px; padding: 7px 10px; border-radius: 8px; background: #f1fbf7; color: #16806a; font-size: 13px; }
.plan-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.plan-summary-grid div { min-height: 82px; padding: 14px; border-radius: 8px; background: #fff7f0; }
.plan-summary-grid span { display: block; color: #836b5e; font-size: 12px; font-weight: 800; }
.plan-summary-grid strong { display: block; margin-top: 8px; color: #211914; font-size: 22px; }
.plan-reason, .response, .soft-note { margin: 0; color: #66584f; line-height: 1.8; }
.response { max-height: 260px; overflow: auto; padding: 14px; border-radius: 8px; background: #fff8f1; white-space: pre-wrap; }
.plan-action-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.plan-action { padding: 0 16px; border: 1px solid #ffd7c1; background: #fff5ed; color: #9e3b13; }
.plan-action-execute { border-color: #ff6b35; background: #ff6b35; color: #fff; }
.plan-action-export { border-color: #cbe9df; background: #effbf7; color: #16735f; }
.candidate-list, .place-list, .execution-panel ol, .issue-panel ul { margin: 0; padding: 0; list-style: none; }
.candidate-list { display: grid; gap: 12px; }
.candidate-item { border: 1px solid #f0ded0; border-radius: 8px; padding: 12px; background: #fffaf6; }
.candidate-item.selected { border-color: #ff8a50; box-shadow: 0 0 0 4px rgb(255 138 80 / 12%); }
.candidate-item button { display: grid; width: 100%; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 0; background: transparent; color: #211914; text-align: left; }
.candidate-item button span, .candidate-item button em { color: #d75017; font-size: 12px; font-style: normal; font-weight: 900; }
.candidate-item button strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.candidate-item > p { margin: 10px 0; color: #6f6259; font-size: 13px; line-height: 1.6; }
.pros-cons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pros-cons div { min-height: 92px; padding: 10px; border-radius: 8px; background: #fff; }
.pros-cons b { color: #211914; font-size: 12px; }
.pros-cons p { margin: 6px 0 0; color: #74675e; font-size: 12px; line-height: 1.55; }
.experience-main { min-width: 0; }
.place-list { display: grid; gap: 14px; }
.place-card { display: grid; grid-template-columns: 238px minmax(0, 1fr); gap: 16px; border: 1px solid rgb(33 25 20 / 8%); border-radius: 8px; padding: 12px; background: #fff; box-shadow: 0 14px 36px rgb(82 45 26 / 7%); }
.image-strip { display: flex; gap: 8px; min-width: 0; height: 178px; overflow-x: auto; border-radius: 8px; background: #f6eadf; scroll-snap-type: x mandatory; }
.image-strip img { flex: 0 0 100%; width: 100%; height: 178px; object-fit: cover; scroll-snap-align: start; }
.place-content { display: grid; align-content: start; gap: 10px; min-width: 0; }
.place-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.station-index { min-height: 28px; padding: 6px 9px; border-radius: 8px; background: #fff1e6; color: #d75017; font-size: 12px; font-weight: 900; }
.place-heading strong { overflow: hidden; color: #211914; font-size: 21px; text-overflow: ellipsis; white-space: nowrap; }
.place-heading em { color: #16806a; font-size: 13px; font-style: normal; font-weight: 900; }
.travel-line { display: flex; flex-wrap: wrap; gap: 8px; }
.travel-line span, .tag-row span { min-height: 28px; padding: 6px 9px; border-radius: 8px; background: #f5f0ea; color: #65574e; font-size: 12px; font-weight: 800; }
.one-line-reason { margin: 0; color: #2f241d; font-weight: 900; line-height: 1.6; }
.reason-group p, .place-address { margin: 0; color: #786b62; font-size: 13px; line-height: 1.65; }
.tag-row, .option-row { display: flex; flex-wrap: wrap; gap: 8px; }
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
.theme-dark .brand, .theme-dark .nav-links a { color: #f7eadf; }
.theme-dark .top-action, .theme-dark .theme-toggle { border-color: #384352; background: #17202b; color: #d7e0eb; }
.theme-dark .top-action strong, .theme-dark .eyebrow, .theme-dark .planner-card-head span, .theme-dark .section-heading span, .theme-dark .progress-title span, .theme-dark .empty-product-state span, .theme-dark .candidate-item button span, .theme-dark .candidate-item button em, .theme-dark .station-index, .theme-dark .issue-panel li strong, .theme-dark .execution-panel li span { color: #ff9868; }
.theme-dark .theme-toggle:hover { border-color: #ff9868; color: #ff9868; }
.theme-dark .hero-section { background: #18212b; }
.theme-dark .hero-copy, .theme-dark .mini-status, .theme-dark .plan-reason, .theme-dark .response, .theme-dark .soft-note, .theme-dark .empty-product-state p, .theme-dark .candidate-item > p, .theme-dark .pros-cons p, .theme-dark .reason-group p, .theme-dark .place-address, .theme-dark .map-empty, .theme-dark .issue-panel li p, .theme-dark .execution-panel li p, .theme-dark .execution-status { color: #b5c0cf; }
.theme-dark .trust-row span, .theme-dark .quick-shell button, .theme-dark .plan-action, .theme-dark .station-index { border-color: #3b4655; background: #1b2632; color: #e7d1c1; }
.theme-dark .planner-card, .theme-dark .progress-strip, .theme-dark .empty-product-state, .theme-dark .plan-main-card, .theme-dark .plan-side-card, .theme-dark .map-card, .theme-dark .issue-panel, .theme-dark .execution-panel, .theme-dark .place-card { border-color: rgb(255 255 255 / 10%); background: #141c26; box-shadow: 0 18px 48px rgb(0 0 0 / 26%); }
.theme-dark .planner-card-head { border-bottom-color: #303c4a; }
.theme-dark .planner-card-head strong, .theme-dark .query-box span, .theme-dark .section-heading h2, .theme-dark .plan-summary-grid strong, .theme-dark .candidate-item button, .theme-dark .pros-cons b, .theme-dark .place-heading strong, .theme-dark .one-line-reason, .theme-dark .issue-panel li span, .theme-dark .execution-panel li strong { color: #edf1f7; }
.theme-dark .query-box textarea, .theme-dark .response { border-color: #3b4655; background: #0f141b; color: #edf1f7; }
.theme-dark .plan-summary-grid div, .theme-dark .progress-strip li, .theme-dark .candidate-item, .theme-dark .pros-cons div, .theme-dark .travel-line span, .theme-dark .tag-row span, .theme-dark .map-empty, .theme-dark .issue-panel li, .theme-dark .step-running { background: #1b2632 !important; }
.theme-dark .progress-strip li p, .theme-dark .plan-summary-grid span, .theme-dark .travel-line span, .theme-dark .tag-row span { color: #c1cad7; }
.theme-dark .candidate-item { border-color: #354252; }
.theme-dark .candidate-item.selected { border-color: #ff9868; box-shadow: 0 0 0 4px rgb(255 152 104 / 14%); }
.theme-dark .section-heading strong, .theme-dark .plan-action-export, .theme-dark .option-row button, .theme-dark .step-completed, .theme-dark .step-done { border-color: #2e6457; background: #122a27 !important; color: #81dbc5; }
.theme-dark .image-strip { background: #101720; }
.theme-dark .error { border-color: #6a3935; background: #321d20; color: #ffb4a7; }
@media (max-width: 1080px) { .hero-shell, .plan-layout, .experience-layout { grid-template-columns: 1fr; } .sticky-side { position: static; } .plan-side-card { order: -1; } }
@media (max-width: 760px) { .topbar-inner, .hero-shell, .quick-shell, .product-shell { padding-right: 16px; padding-left: 16px; } .nav-links, .top-action { display: none; } .topbar-inner { gap: 12px; } .hero-section { padding-top: 30px; } .hero-copy-block h1 { font-size: 40px; } .hero-copy { font-size: 16px; } .search-actions, .plan-action-row { align-items: stretch; flex-direction: column; } .primary-button, .plan-action { width: 100%; } .empty-product-state, .place-card { grid-template-columns: 1fr; } .plan-summary-grid { grid-template-columns: 1fr 1fr; } .place-heading { grid-template-columns: 1fr; } .place-heading strong { white-space: normal; } .candidate-item button { grid-template-columns: 1fr; } }
</style>
