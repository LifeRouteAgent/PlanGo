<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import AmapTripMap from "../components/AmapTripMap.vue";
import { getDataSourceStatus, planTrip } from "../services/api";
import type { DataSourceStatus, PoiItem, RankedPlan, RouteSegment, TimelineItem, TripPlanResponse } from "../types";

// 默认输入覆盖“朋友 + 吃饭 + 电影 + 时间/预算约束”，用于快速验证 Gate 5。
const query = ref("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元");
const loading = ref(false);
const errorMessage = ref("");
const result = ref<TripPlanResponse | null>(null);
const dataSource = ref<DataSourceStatus | null>(null);
const streamedResponse = ref("");
let streamTimer: number | undefined;

const hasPlan = computed(() => Boolean(result.value?.selected_plan?.id));
const selectedPlan = computed(() => result.value?.selected_plan ?? null);
const placeCards = computed(() => buildPlaceCards(selectedPlan.value));
const collectorLog = computed(() => result.value?.logs.find((log) => log.includes("POI Collector")));
const tableTotal = computed(() => {
  if (!dataSource.value) {
    return 0;
  }
  return Object.values(dataSource.value.table_counts).reduce((sum, value) => sum + value, 0);
});

watch(
  () => result.value?.response_text ?? "",
  (text) => {
    startResponseStream(text);
  }
);
const scoreItems = computed(() => {
  const breakdown = selectedPlan.value?.score_breakdown;
  if (!breakdown) {
    return [];
  }
  return [
    ["偏好匹配", breakdown.preference_match],
    ["距离合理", breakdown.distance_reasonable],
    ["时间可行", breakdown.time_feasible],
    ["评分热度", breakdown.rating_heat],
    ["预算适配", breakdown.budget_fit],
    ["场景适配", breakdown.scene_fit],
    ["风险扣分", breakdown.warning_penalty]
  ].filter(([, value]) => typeof value === "number") as Array<[string, number]>;
});

onMounted(async () => {
  // 页面加载时先读取数据源状态，方便确认当前使用 MySQL 还是 Mock。
  try {
    dataSource.value = await getDataSourceStatus();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "数据源状态请求失败";
  }
});

async function submitPlan() {
  errorMessage.value = "";
  loading.value = true;
  streamedResponse.value = "";
  stopResponseStream();

  try {
    result.value = await planTrip({
      user_query: query.value,
      max_replanning_count: 2
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "规划请求失败";
  } finally {
    loading.value = false;
  }
}

onBeforeUnmount(() => {
  stopResponseStream();
});

function startResponseStream(text: string) {
  stopResponseStream();
  streamedResponse.value = "";
  if (!text) {
    return;
  }

  let index = 0;
  // 当前后端是同步接口，所以这里做前端渐进式渲染；后续切换 SSE 时保留同一个展示状态即可。
  streamTimer = window.setInterval(() => {
    const chunkSize = text.length > 360 ? 4 : 2;
    streamedResponse.value += text.slice(index, index + chunkSize);
    index += chunkSize;
    if (index >= text.length) {
      streamedResponse.value = text;
      stopResponseStream();
    }
  }, 18);
}

function stopResponseStream() {
  if (streamTimer !== undefined) {
    window.clearInterval(streamTimer);
    streamTimer = undefined;
  }
}

interface PlaceCard {
  id: string;
  order: number;
  name: string;
  rating?: number;
  reasonLines: string[];
  distanceText: string;
  transportText: string;
  durationText: string;
  address: string;
  tags: string[];
  images: string[];
}

function buildPlaceCards(plan: RankedPlan | null): PlaceCard[] {
  if (!plan?.items?.length) {
    return [];
  }

  return plan.items.map((item, index) => {
    const timeline = findTimelineForItem(plan.timeline ?? [], item, index);
    const segment = index > 0 ? plan.route_segments?.[index - 1] : undefined;
    const reasonLines = buildReasonLines(item);

    return {
      id: item.id,
      order: index + 1,
      name: item.name,
      rating: typeof item.rating === "number" && item.rating > 0 ? item.rating : undefined,
      reasonLines,
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
  const source = item.reason || `${item.subcategory || "本地生活"} · ${item.tags?.slice(0, 2).join("、") || "适合当前行程"}`;
  const parts = source
    .split(/[。；;，,]/)
    .map((part) => part.trim())
    .filter(Boolean);
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
    return typeof distance === "number" && distance > 0 ? `${distance.toFixed(2)} km` : "起点未指定，距离待补充";
  }
  const distance = segment?.distance_km ?? timeline?.distance_from_previous_km;
  return typeof distance === "number" ? `${distance.toFixed(2)} km` : "距离待补充";
}

function formatTravelDuration(index: number, timeline?: TimelineItem, segment?: RouteSegment) {
  if (index === 0) {
    const minutes = timeline?.travel_from_previous_minutes;
    return typeof minutes === "number" && minutes > 0 ? `${minutes} 分钟` : "到第一站耗时待确认";
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
  return labels[mode ?? ""] ?? mode ?? "交通方式待确认";
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
  const themes: Record<string, [string, string]> = {
    poi_restaurant: ["#fef3c7", "#b45309"],
    poi_entertainment: ["#e0f2fe", "#0369a1"],
    poi_activity: ["#dcfce7", "#15803d"],
    poi_attraction: ["#ede9fe", "#6d28d9"],
    poi_shopping: ["#ffe4e6", "#be123c"],
    poi_fitness: ["#ccfbf1", "#0f766e"],
    poi_beauty: ["#fae8ff", "#a21caf"]
  };
  const [background, foreground] = themes[item.category] ?? ["#e5e7eb", "#334155"];
  return [0, 1, 2].map((offset) => {
    const label = escapeSvgText(offset === 0 ? item.name : item.subcategory || "本地生活");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="${background}"/><rect x="28" y="28" width="584" height="304" rx="20" fill="white" fill-opacity=".62"/><text x="50%" y="48%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="${foreground}">${label}</text><text x="50%" y="62%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="${foreground}" opacity=".72">图片待接入</text></svg>`;
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
  });
}

function escapeSvgText(text: string) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
</script>

<template>
  <main class="workspace">
    <section class="composer">
      <div>
        <p class="eyebrow">LifeRouteAgent</p>
        <h1>本地生活周末规划</h1>
        <p class="intro">输入自然语言需求，后端 LangGraph DAG 会返回模拟方案、日志和异常状态。</p>
      </div>

      <label class="query-box">
        <span>用户需求</span>
        <textarea v-model="query" rows="5" />
      </label>

      <button :disabled="loading || !query.trim()" @click="submitPlan">
        {{ loading ? "规划中..." : "生成行程" }}
      </button>

      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

      <div class="source-card">
        <span>数据源</span>
        <strong>{{ dataSource?.source ?? "检测中" }}</strong>
        <p v-if="dataSource?.enabled">数据库：{{ dataSource.database_name }}，共 {{ tableTotal }} 条 POI</p>
        <p v-else-if="dataSource?.error">数据库异常：{{ dataSource.error }}</p>
        <p v-else>当前使用 Mock 候选数据。</p>
      </div>
    </section>

    <section class="result-grid">
      <article class="panel plan-panel">
        <div class="panel-header">
          <h2>方案结果</h2>
          <span v-if="result">{{ result.need_clarification ? "需要补充信息" : result.execution_status }}</span>
        </div>

        <pre v-if="result?.response_text" class="response">{{ streamedResponse }}</pre>
        <p v-else class="empty">还没有生成方案。</p>

        <section v-if="placeCards.length" class="place-section" aria-label="方案地点">
          <div class="section-title">
            <h3>方案地点</h3>
            <span>{{ placeCards.length }} 站</span>
          </div>

          <ol class="place-list">
            <li v-for="card in placeCards" :key="card.id" class="place-card">
              <div class="image-strip" :aria-label="`${card.name} 图片`">
                <img
                  v-for="(image, imageIndex) in card.images"
                  :key="`${card.id}-${imageIndex}`"
                  :src="image"
                  :alt="`${card.name} 图片 ${imageIndex + 1}`"
                  loading="lazy"
                />
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

                <p class="reason-line" v-for="line in card.reasonLines" :key="line">{{ line }}</p>
                <p class="place-address">{{ card.address }}</p>

                <div v-if="card.tags.length" class="tag-row">
                  <span v-for="tag in card.tags.slice(0, 4)" :key="tag">{{ tag }}</span>
                </div>
              </div>
            </li>
          </ol>
        </section>

        <div v-if="selectedPlan?.id" class="metrics-grid">
          <div>
            <span>方案评分</span>
            <strong>{{ selectedPlan.plan_score ?? "待计算" }}</strong>
          </div>
          <div>
            <span>总时长</span>
            <strong>{{ selectedPlan.total_duration_minutes ?? 0 }} 分钟</strong>
          </div>
          <div>
            <span>交通</span>
            <strong>{{ selectedPlan.route_minutes ?? 0 }} 分钟</strong>
          </div>
          <div>
            <span>预算</span>
            <strong>{{ selectedPlan.estimated_budget ?? 0 }} 元</strong>
          </div>
        </div>

        <div v-if="scoreItems.length" class="score-breakdown">
          <strong>评分拆解</strong>
          <div v-for="[label, value] in scoreItems" :key="label" class="score-row">
            <span>{{ label }}</span>
            <meter min="0" max="1" :value="value" />
            <em>{{ value.toFixed(2) }}</em>
          </div>
        </div>

        <div v-if="result?.need_clarification" class="issues">
          <strong>缺失条件</strong>
          <ul>
            <li v-for="item in result.missing_constraints" :key="item">{{ item }}</li>
          </ul>
        </div>

        <p v-if="collectorLog" class="collector-log">{{ collectorLog }}</p>

        <div v-if="result?.errors.length" class="issues">
          <strong>校验状态</strong>
          <ul>
            <li v-for="item in result.errors" :key="`${item.code}-${item.source}`">
              <b>{{ item.severity === "warning" ? "提醒" : "错误" }}：</b>{{ item.message }}
              <span>建议：{{ item.suggestion }}</span>
            </li>
          </ul>
        </div>
      </article>

      <article class="panel">
        <div class="panel-header">
          <h2>地图与时间线</h2>
        </div>
        <AmapTripMap v-if="hasPlan && result" :plan="result.selected_plan" />
        <p v-else class="empty">生成方案后展示路线占位和时间线。</p>
      </article>

      <article class="panel logs-panel">
        <div class="panel-header">
          <h2>DAG 日志</h2>
          <span>{{ result?.logs.length ?? 0 }} 条</span>
        </div>
        <ol v-if="result?.logs.length">
          <li v-for="log in result.logs" :key="log">{{ log }}</li>
        </ol>
        <p v-else class="empty">等待后端返回节点日志。</p>
      </article>

      <article v-if="result?.ranked_plans.length" class="panel plans-panel">
        <div class="panel-header">
          <h2>候选方案</h2>
          <span>{{ result.ranked_plans.length }} 个</span>
        </div>
        <ol class="candidate-list">
          <li v-for="plan in result.ranked_plans" :key="plan.id">
            <div>
              <strong>{{ plan.title ?? plan.id }}</strong>
              <p>
                评分 {{ plan.plan_score ?? "待计算" }} ·
                {{ plan.total_duration_minutes ?? 0 }} 分钟 ·
                交通 {{ plan.route_minutes ?? 0 }} 分钟 ·
                预算 {{ plan.estimated_budget ?? 0 }} 元
              </p>
            </div>
          </li>
        </ol>
      </article>
    </section>
  </main>
</template>

<style scoped>
.workspace {
  display: grid;
  grid-template-columns: minmax(300px, 420px) 1fr;
  gap: 24px;
  min-height: 100vh;
  padding: 28px;
  background: #eef2f7;
  color: #162033;
}

.composer,
.panel {
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: white;
  box-shadow: 0 10px 30px rgb(23 32 51 / 8%);
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 20px;
  align-self: start;
  padding: 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1f6feb;
  font-size: 13px;
  font-weight: 700;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 12px;
  font-size: 28px;
}

h2 {
  margin-bottom: 0;
  font-size: 18px;
}

.intro {
  margin-bottom: 0;
  color: #687386;
  line-height: 1.6;
}

.query-box {
  display: grid;
  gap: 8px;
  color: #344052;
  font-weight: 700;
}

textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid #c8d1df;
  border-radius: 8px;
  padding: 12px;
  color: #162033;
  font: inherit;
  line-height: 1.6;
}

button {
  border: 0;
  border-radius: 8px;
  padding: 12px 16px;
  background: #1f6feb;
  color: white;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.error {
  margin-bottom: 0;
  color: #b42318;
}

.source-card {
  display: grid;
  gap: 6px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 12px;
  background: #f8fafc;
}

.source-card span {
  color: #687386;
  font-size: 12px;
  font-weight: 700;
}

.source-card strong {
  color: #172033;
}

.source-card p,
.collector-log {
  margin: 0;
  color: #687386;
  font-size: 13px;
  line-height: 1.5;
}

.result-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(320px, 1fr);
  gap: 20px;
}

.panel {
  padding: 20px;
}

.plan-panel,
.logs-panel {
  grid-column: span 1;
}

.logs-panel {
  grid-column: 1 / -1;
}

.plans-panel {
  grid-column: 1 / -1;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-header span {
  border-radius: 999px;
  background: #eef4ff;
  color: #1f6feb;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
}

.response {
  white-space: pre-wrap;
  margin: 0;
  color: #263246;
  font-family: inherit;
  line-height: 1.7;
}

.collector-log {
  margin-top: 16px;
  border-top: 1px solid #e4e9f1;
  padding-top: 12px;
}

.place-section {
  display: grid;
  gap: 14px;
  margin-top: 20px;
  border-top: 1px solid #e4e9f1;
  padding-top: 18px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title h3 {
  margin: 0;
  color: #172033;
  font-size: 16px;
}

.section-title span {
  color: #687386;
  font-size: 13px;
  font-weight: 700;
}

.place-list {
  display: grid;
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.place-card {
  display: grid;
  grid-template-columns: minmax(180px, 240px) 1fr;
  overflow: hidden;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
}

.image-strip {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 100%;
  min-height: 180px;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
  scroll-snap-type: inline mandatory;
  background: #f1f5f9;
}

.image-strip img {
  width: 100%;
  height: 100%;
  min-height: 180px;
  object-fit: cover;
  scroll-snap-align: start;
}

.place-content {
  display: grid;
  gap: 10px;
  padding: 14px;
}

.place-heading {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
}

.station-index {
  border-radius: 999px;
  background: #eef4ff;
  color: #1f6feb;
  padding: 3px 8px;
  font-size: 12px;
  font-weight: 700;
}

.place-heading strong {
  color: #172033;
  font-size: 17px;
  line-height: 1.35;
}

.place-heading em {
  color: #92400e;
  font-size: 12px;
  font-style: normal;
  font-weight: 700;
}

.travel-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.travel-line span {
  border: 1px solid #d8dee8;
  border-radius: 999px;
  padding: 4px 8px;
  background: #f8fafc;
  color: #344052;
  font-size: 12px;
  font-weight: 700;
}

.reason-line {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #263246;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.place-address {
  margin: 0;
  color: #687386;
  font-size: 13px;
  line-height: 1.5;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-row span {
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  padding: 3px 7px;
  font-size: 12px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.metrics-grid div {
  display: grid;
  gap: 4px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 10px;
  background: #f8fafc;
}

.metrics-grid span {
  color: #687386;
  font-size: 12px;
  font-weight: 700;
}

.metrics-grid strong {
  color: #172033;
}

.score-breakdown {
  display: grid;
  gap: 10px;
  margin-top: 18px;
  border-top: 1px solid #e4e9f1;
  padding-top: 16px;
}

.score-row {
  display: grid;
  grid-template-columns: 72px 1fr 44px;
  gap: 10px;
  align-items: center;
  color: #344052;
  font-size: 13px;
}

.score-row meter {
  width: 100%;
}

.score-row em {
  color: #687386;
  font-style: normal;
  text-align: right;
}

.empty {
  margin-bottom: 0;
  color: #687386;
}

.issues {
  margin-top: 20px;
  border-top: 1px solid #e4e9f1;
  padding-top: 16px;
}

.issues ul,
.logs-panel ol {
  margin-bottom: 0;
  padding-left: 20px;
}

.issues li span {
  display: block;
  margin-top: 4px;
  color: #687386;
  font-size: 13px;
}

.logs-panel li {
  margin-bottom: 8px;
  color: #344052;
}

.candidate-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding-left: 20px;
}

.candidate-list p {
  margin: 4px 0 0;
  color: #687386;
  font-size: 13px;
}

@media (max-width: 920px) {
  .workspace,
  .result-grid {
    grid-template-columns: 1fr;
  }

  .logs-panel,
  .plans-panel {
    grid-column: auto;
  }

  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .place-card {
    grid-template-columns: 1fr;
  }

  .place-heading {
    grid-template-columns: 1fr;
  }
}
</style>
