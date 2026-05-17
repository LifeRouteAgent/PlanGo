<script setup lang="ts">
import type { RankedPlan } from "../types";

defineProps<{
  plan: RankedPlan;
}>();
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

    <ol v-if="plan.timeline?.length" class="timeline-list">
      <li v-for="item in plan.timeline" :key="`${item.order}-${item.title}`">
        <span>{{ item.order }}</span>
        <div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.start_time }} · {{ item.address }}</p>
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
</style>
