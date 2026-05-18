<script setup lang="ts">
import { computed } from "vue";
import type { RankedPlan } from "../types";

const props = defineProps<{
  plan: RankedPlan;
}>();

const routeModes = computed(() => {
  const modes =
    props.plan.route_segments
      ?.map((segment) => String(segment.transport_mode ?? ""))
      .filter(Boolean) ?? [];
  return [...new Set(modes)];
});

function formatTransport(mode?: string) {
  const labels: Record<string, string> = {
    start: "起点",
    walk: "步行",
    taxi: "打车",
    transit_or_taxi: "地铁/打车",
    cross_district_taxi: "跨区打车",
    forced_timeout: "超时模拟"
  };
  return labels[mode ?? ""] ?? mode ?? "待定";
}
</script>

<template>
  <section class="map-panel">
    <div class="map-surface">
      <div class="map-grid" />
      <div class="map-content">
        <p class="map-title">高德地图预留区域</p>
        <p class="map-subtitle">后续接入 AMap JS API 后展示路线、POI 点位和通勤时间。</p>
      </div>
    </div>

    <div class="route-summary">
      <div>
        <span>总距离</span>
        <strong>{{ plan.total_distance_km ?? 0 }} km</strong>
      </div>
      <div>
        <span>交通时间</span>
        <strong>{{ plan.route_minutes ?? 0 }} 分钟</strong>
      </div>
      <div>
        <span>交通方式</span>
        <strong>{{ routeModes.length ? routeModes.map(formatTransport).join(" / ") : "无需换乘" }}</strong>
      </div>
    </div>

    <ol v-if="plan.timeline?.length" class="timeline-list">
      <li v-for="item in plan.timeline" :key="`${item.order}-${item.title}`">
        <span>{{ item.order }}</span>
        <div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.start_time }} - {{ item.end_time ?? "待定" }} · 停留 {{ item.stay_minutes ?? 0 }} 分钟</p>
          <p v-if="item.order > 1">
            {{ formatTransport(item.transport_mode) }} {{ item.travel_from_previous_minutes ?? 0 }} 分钟
            · {{ item.distance_from_previous_km ?? 0 }} km
          </p>
          <p>{{ item.address }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.map-panel {
  display: grid;
  gap: 16px;
}

.map-surface {
  position: relative;
  min-height: 260px;
  overflow: hidden;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #f6f8fb;
}

.map-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(#e4e9f1 1px, transparent 1px),
    linear-gradient(90deg, #e4e9f1 1px, transparent 1px);
  background-size: 28px 28px;
}

.map-content {
  position: relative;
  display: grid;
  min-height: 260px;
  place-items: center;
  padding: 24px;
  text-align: center;
}

.map-title {
  margin: 0 0 8px;
  color: #162033;
  font-size: 18px;
  font-weight: 700;
}

.map-subtitle {
  max-width: 360px;
  margin: 0;
  color: #687386;
  line-height: 1.6;
}

.timeline-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.route-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.route-summary div {
  display: grid;
  gap: 4px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 10px;
  background: #f8fafc;
}

.route-summary span {
  color: #687386;
  font-size: 12px;
  font-weight: 700;
}

.route-summary strong {
  color: #172033;
  font-size: 14px;
}

.timeline-list li {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 10px;
  align-items: start;
}

.timeline-list span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: #1f6feb;
  color: white;
  font-size: 13px;
  font-weight: 700;
}

.timeline-list strong {
  color: #172033;
}

.timeline-list p {
  margin: 4px 0 0;
  color: #687386;
  font-size: 13px;
}

@media (max-width: 920px) {
  .route-summary {
    grid-template-columns: 1fr;
  }
}
</style>
