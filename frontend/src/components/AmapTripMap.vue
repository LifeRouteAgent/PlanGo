<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { PoiItem, RankedPlan } from "../types";

const props = defineProps<{
  plan: RankedPlan;
}>();

type AMapNamespace = {
  Map: new (container: HTMLElement, options: Record<string, unknown>) => AMapMap;
  Marker: new (options: Record<string, unknown>) => AMapMarker;
  Polyline: new (options: Record<string, unknown>) => AMapPolyline;
  Pixel: new (x: number, y: number) => unknown;
  LngLat: new (lng: number, lat: number) => unknown;
};

type AMapMap = {
  add: (overlay: AMapMarker | AMapPolyline | Array<AMapMarker | AMapPolyline>) => void;
  remove: (overlay: AMapMarker | AMapPolyline | Array<AMapMarker | AMapPolyline>) => void;
  setFitView: (overlays?: Array<AMapMarker | AMapPolyline>, immediately?: boolean, avoid?: number[], maxZoom?: number) => void;
  destroy: () => void;
};

type AMapMarker = unknown;
type AMapPolyline = unknown;

declare global {
  interface Window {
    AMap?: AMapNamespace;
    _AMapSecurityConfig?: {
      securityJsCode?: string;
    };
    __lifeRouteAmapLoader?: Promise<AMapNamespace>;
  }
}

const mapContainer = ref<HTMLDivElement | null>(null);
const mapError = ref("");
const mapLoaded = ref(false);
const amapKey = ref(String(import.meta.env.VITE_AMAP_KEY ?? ""));
const amapSecurityCode = ref(String(import.meta.env.VITE_AMAP_SECURITY_JS_CODE ?? ""));
const mapEnabled = computed(() => Boolean(amapKey.value));

let mapInstance: AMapMap | null = null;
let activeOverlays: Array<AMapMarker | AMapPolyline> = [];

const routeModes = computed(() => {
  const modes =
    props.plan.route_segments
      ?.map((segment) => String(segment.transport_mode ?? ""))
      .filter(Boolean) ?? [];
  return [...new Set(modes)];
});

const mapPoints = computed(() => {
  const timeline = props.plan.timeline ?? [];
  return (props.plan.items ?? [])
    .map((item, index) => {
      const lat = Number(item.lat);
      const lon = Number(item.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat === 0 || lon === 0) {
        return null;
      }
      return {
        item,
        order: index + 1,
        lnglat: [lon, lat] as [number, number],
        time: timeline[index] ? `${timeline[index].start_time}-${timeline[index].end_time ?? "待定"}` : "",
      };
    })
    .filter(Boolean) as Array<{
      item: PoiItem;
      order: number;
      lnglat: [number, number];
      time: string;
    }>;
});

watch(
  () => props.plan.id,
  async () => {
    await renderMap();
  }
);

onMounted(async () => {
  await loadClientConfig();
  await renderMap();
});

onBeforeUnmount(() => {
  clearMap();
  mapInstance?.destroy();
  mapInstance = null;
});

async function renderMap() {
  mapError.value = "";
  if (!mapEnabled.value || !mapContainer.value || !mapPoints.value.length) {
    return;
  }

  await nextTick();
  try {
    const AMap = await loadAmap();
    if (!mapContainer.value) {
      return;
    }
    if (!mapInstance) {
      mapInstance = new AMap.Map(mapContainer.value, {
        zoom: 12,
        viewMode: "2D",
        resizeEnable: true,
        mapStyle: "amap://styles/normal",
      });
    }
    drawPlan(AMap);
    mapLoaded.value = true;
  } catch (error) {
    mapError.value = error instanceof Error ? error.message : "高德地图加载失败";
    mapLoaded.value = false;
  }
}

function drawPlan(AMap: AMapNamespace) {
  if (!mapInstance) {
    return;
  }
  clearMap();

  const markers = mapPoints.value.map((point) => {
    return new AMap.Marker({
      position: new AMap.LngLat(point.lnglat[0], point.lnglat[1]),
      title: point.item.name,
      offset: new AMap.Pixel(-13, -34),
      content: markerHtml(point.order, point.item.name),
    });
  });

  const polyline =
    mapPoints.value.length > 1
      ? new AMap.Polyline({
          path: mapPoints.value.map((point) => point.lnglat),
          strokeColor: "#ff7a00",
          strokeWeight: 5,
          strokeOpacity: 0.85,
          lineJoin: "round",
          lineCap: "round",
        })
      : null;

  activeOverlays = polyline ? [...markers, polyline] : markers;
  mapInstance.add(activeOverlays);
  mapInstance.setFitView(activeOverlays, false, [48, 48, 48, 48], 15);
}

function clearMap() {
  if (mapInstance && activeOverlays.length) {
    mapInstance.remove(activeOverlays);
  }
  activeOverlays = [];
}

function loadAmap(): Promise<AMapNamespace> {
  if (window.AMap) {
    return Promise.resolve(window.AMap);
  }
  if (window.__lifeRouteAmapLoader) {
    return window.__lifeRouteAmapLoader;
  }
  if (!amapKey.value) {
    return Promise.reject(new Error("缺少高德地图 Key，无法加载地图。"));
  }
  if (amapSecurityCode.value) {
    window._AMapSecurityConfig = {
      securityJsCode: amapSecurityCode.value,
    };
  }

  window.__lifeRouteAmapLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(amapKey.value)}`;
    script.async = true;
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap);
      } else {
        reject(new Error("高德地图脚本已加载，但 AMap 对象不存在。"));
      }
    };
    script.onerror = () => reject(new Error("高德地图脚本加载失败，请检查 key、域名白名单或网络。"));
    document.head.appendChild(script);
  });
  return window.__lifeRouteAmapLoader;
}

async function loadClientConfig() {
  try {
    const response = await fetch("/trip/client-config");
    if (!response.ok) {
      return;
    }
    const config = (await response.json()) as {
      amap_key?: string;
      amap_security_js_code?: string;
    };
    if (config.amap_key) {
      amapKey.value = config.amap_key;
    }
    if (config.amap_security_js_code) {
      amapSecurityCode.value = config.amap_security_js_code;
    }
  } catch {
    // 读取后端运行配置失败时保留 Vite 环境变量 fallback，不阻塞页面渲染。
  }
}

function markerHtml(order: number, name: string) {
  const safeName = escapeHtml(name);
  return `
    <div class="amap-stop-marker">
      <span>${order}</span>
      <strong>${safeName}</strong>
    </div>
  `;
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTransport(mode?: string) {
  const labels: Record<string, string> = {
    start: "起点",
    walk: "步行",
    taxi: "打车",
    transit_or_taxi: "地铁/打车",
    cross_district_taxi: "跨区打车",
    forced_timeout: "超时模拟",
  };
  return labels[mode ?? ""] ?? mode ?? "待定";
}
</script>

<template>
  <section class="map-panel">
    <div class="map-surface">
      <div v-if="mapEnabled && mapPoints.length" ref="mapContainer" class="amap-container" />

      <div v-else class="map-fallback">
        <div class="map-grid" />
        <div class="map-content">
          <p class="map-title">高德地图未启用</p>
          <p class="map-subtitle">
            配置 <code>backend/config.local.json</code> 的 <code>AMAP_API_KEY</code> 后会显示真实地图、POI 点位和路线连线。当前仍可查看下方时间线。
          </p>
        </div>
      </div>

      <div v-if="mapEnabled && !mapLoaded && !mapError && mapPoints.length" class="map-loading">
        地图加载中...
      </div>
      <div v-if="mapError" class="map-error">{{ mapError }}</div>
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

    <ol v-if="mapPoints.length" class="stop-list">
      <li v-for="point in mapPoints" :key="point.item.id">
        <span>{{ point.order }}</span>
        <div>
          <strong>{{ point.item.name }}</strong>
          <p>{{ point.time || "时间待定" }} · {{ point.item.address }}</p>
        </div>
      </li>
    </ol>

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
.map-panel { display: grid; gap: 16px; }
.map-surface { position: relative; min-height: 300px; overflow: hidden; border: 1px solid #d8dee8; border-radius: 8px; background: #f6f8fb; }
.amap-container, .map-fallback { min-height: 300px; }
.amap-container { width: 100%; height: 300px; }
.map-grid { position: absolute; inset: 0; background-image: linear-gradient(#e4e9f1 1px, transparent 1px), linear-gradient(90deg, #e4e9f1 1px, transparent 1px); background-size: 28px 28px; }
.map-content { position: relative; display: grid; min-height: 300px; place-items: center; padding: 24px; text-align: center; }
.map-title { margin: 0 0 8px; color: #162033; font-size: 18px; font-weight: 700; }
.map-subtitle { max-width: 360px; margin: 0; color: #5d6b7c; font-size: 13px; line-height: 1.6; }
.map-subtitle code { padding: 2px 5px; border-radius: 4px; background: #fff1df; color: #a64a00; }
.map-loading, .map-error { position: absolute; right: 12px; bottom: 12px; max-width: calc(100% - 24px); border-radius: 8px; padding: 8px 10px; font-size: 12px; font-weight: 700; }
.map-loading { background: rgb(255 255 255 / 86%); color: #334155; }
.map-error { background: #fff1f0; color: #c2410c; }
.route-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.route-summary div { min-height: 70px; padding: 12px; border: 1px solid #e5eaf2; border-radius: 8px; background: #fff; }
.route-summary span { display: block; color: #64748b; font-size: 12px; font-weight: 700; }
.route-summary strong { display: block; margin-top: 8px; color: #162033; font-size: 16px; }
.stop-list, .timeline-list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.stop-list li, .timeline-list li { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 10px; align-items: start; padding: 10px; border: 1px solid #e5eaf2; border-radius: 8px; background: #fff; }
.stop-list li > span, .timeline-list li > span { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: #ff7a00; color: #fff; font-size: 12px; font-weight: 800; }
.stop-list strong, .timeline-list strong { display: block; color: #162033; font-size: 14px; }
.stop-list p, .timeline-list p { margin: 4px 0 0; color: #617086; font-size: 12px; line-height: 1.5; }
:global(.amap-stop-marker) { display: inline-flex; align-items: center; gap: 6px; max-width: 180px; border: 2px solid #ffffff; border-radius: 999px; background: #ff7a00; box-shadow: 0 6px 16px rgb(0 0 0 / 20%); color: #ffffff; padding: 5px 9px 5px 5px; font-size: 12px; font-weight: 800; white-space: nowrap; }
:global(.amap-stop-marker span) { display: grid; width: 20px; height: 20px; place-items: center; border-radius: 50%; background: #ffffff; color: #ff7a00; }
:global(.amap-stop-marker strong) { overflow: hidden; text-overflow: ellipsis; }
:global(.theme-dark) .map-surface, :global(.theme-dark) .route-summary div, :global(.theme-dark) .stop-list li, :global(.theme-dark) .timeline-list li { border-color: #394657; background: #101720; }
:global(.theme-dark) .map-grid { background-image: linear-gradient(#273545 1px, transparent 1px), linear-gradient(90deg, #273545 1px, transparent 1px); }
:global(.theme-dark) .map-title, :global(.theme-dark) .route-summary strong, :global(.theme-dark) .stop-list strong, :global(.theme-dark) .timeline-list strong { color: #edf1f7; }
:global(.theme-dark) .map-subtitle, :global(.theme-dark) .route-summary span, :global(.theme-dark) .stop-list p, :global(.theme-dark) .timeline-list p { color: #b5c0cf; }
@media (max-width: 920px) { .route-summary { grid-template-columns: 1fr; } }
</style>
