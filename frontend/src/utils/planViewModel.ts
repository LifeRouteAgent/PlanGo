import type { Plan, PlanStep, RouteSegment } from "../types/agent";

export interface PlanMetric {
  label: string;
  value: string;
  hint: string;
}

export interface PlanStopView {
  id: string;
  order: number;
  label: string;
  time: string;
  title: string;
  address: string;
  reason: string;
  cost: number;
  traffic: string;
  imageUrl: string | null;
  tags: string[];
  lat: number | null;
  lng: number | null;
  rating: string | null;
  raw: PlanStep;
}

export interface PlanMapMarker {
  id: string;
  label: string;
  title: string;
  time: string;
  lat: number;
  lng: number;
}

export interface PlanRouteSummary {
  distanceText: string;
  routeMinutesText: string;
  transportModesText: string;
  stopSequenceText: string;
}

export interface PlanViewModel {
  id: string;
  badge: string;
  styleTag: string;
  title: string;
  audience: string;
  durationText: string;
  budgetText: string;
  distanceText: string;
  reason: string;
  pros: string[];
  cons: string[];
  metrics: PlanMetric[];
  timelinePreview: string[];
  summaryStops: PlanStopView[];
  stops: PlanStopView[];
  mapMarkers: PlanMapMarker[];
  routeSummary: PlanRouteSummary;
  routeSegments: RouteSegment[];
  raw: Plan;
}

function scenarioText(plan: Plan) {
  if (plan.scenario === "family") return "家庭 / 亲子";
  if (plan.scenario === "friends") return "朋友聚会";
  if (plan.scenario === "couple") return "情侣约会";
  return "本地生活";
}

function minuteText(minutes: number) {
  if (!minutes) return "待确认";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} 分钟`;
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
}

function currencyText(value: number) {
  if (!value) return "预算待估";
  return `约 ¥${Math.round(value)}`;
}

function distanceText(plan: Plan) {
  const routeDistance =
    plan.recommendation?.distance_km ||
    plan.route?.segments?.reduce((sum, segment) => sum + (segment.distance_km ?? 0), 0) ||
    0;
  return routeDistance ? `${routeDistance.toFixed(1)} 公里` : "距离待估";
}

function timeRange(step: PlanStep) {
  if (step.start_time && step.end_time && step.start_time !== "--:--" && step.end_time !== "--:--") {
    return `${step.start_time} - ${step.end_time}`;
  }
  if (step.start_time && step.start_time !== "--:--") {
    return step.start_time;
  }
  return "时间待定";
}

function stepTraffic(step: PlanStep) {
  const route = step.metadata?.route as
    | { distance_km?: number; duration_min?: number; mode?: string }
    | undefined;
  if (route?.duration_min || route?.distance_km) {
    const mode = route.mode || "交通";
    const distance = route.distance_km ? `${route.distance_km.toFixed(1)} 公里` : "距离待估";
    const duration = route.duration_min ? `约 ${route.duration_min} 分钟` : "耗时待估";
    return `${mode} · ${distance} · ${duration}`;
  }
  return step.detail?.traffic || "交通信息待确认";
}

function stepToStop(step: PlanStep, index: number): PlanStopView {
  const rating = step.metadata?.rating;
  return {
    id: step.target_id || `${index}`,
    order: index + 1,
    label: String.fromCharCode(65 + index),
    time: timeRange(step),
    title: step.title,
    address: step.location?.address || step.detail?.address || "地址待确认",
    reason: step.reason || step.detail?.description || "符合本次偏好和行程节奏。",
    cost: step.cost || step.detail?.cost || 0,
    traffic: stepTraffic(step),
    imageUrl: step.detail?.image_url ?? null,
    tags: step.detail?.tags?.filter(Boolean).slice(0, 5) ?? [],
    lat: step.location?.lat ?? null,
    lng: step.location?.lng ?? null,
    rating: rating === undefined || rating === null ? null : String(rating),
    raw: step
  };
}

function styleTagFromBadge(badge: string, indexHint: number) {
  if (badge.includes("省")) return "预算友好";
  if (badge.includes("近")) return "低移动";
  if (badge.includes("轻")) return "轻松节奏";
  if (indexHint === 0) return "主推方案";
  if (indexHint === 1) return "备选组合";
  return "差异路线";
}

function routeSummary(plan: Plan, stops: PlanStopView[], distance: string): PlanRouteSummary {
  const routeMinutes = plan.route?.segments?.reduce((sum, segment) => sum + (segment.duration_min ?? 0), 0) ?? 0;
  const modes = Array.from(new Set(plan.route?.segments?.map((segment) => segment.transport_mode).filter(Boolean) ?? []));
  return {
    distanceText: distance,
    routeMinutesText: routeMinutes ? `约 ${routeMinutes} 分钟` : "交通待确认",
    transportModesText: modes.length ? modes.join(" / ") : "步行 / 打车",
    stopSequenceText: stops.map((stop) => stop.label).join(" → ")
  };
}

export function planToViewModel(plan: Plan, badge = "推荐", indexHint = 0): PlanViewModel {
  const stops = plan.steps.map(stepToStop);
  const distance = distanceText(plan);
  const reason =
    plan.rationale?.[0] ||
    plan.recommendation?.tags?.join(" · ") ||
    plan.share_message ||
    "根据时间、预算、距离和偏好生成的可执行方案。";
  const pros = plan.rationale?.slice(0, 3).filter(Boolean) ?? [];
  const cons = plan.risk_flags?.slice(0, 3).filter(Boolean) ?? [];
  const duration = minuteText(plan.total_duration_min);
  const budget = currencyText(plan.total_cost);

  return {
    id: plan.id || "plan-main",
    badge,
    styleTag: styleTagFromBadge(badge, indexHint),
    title: plan.recommendation?.title || "PlanGo 本地生活方案",
    audience: scenarioText(plan),
    durationText: duration,
    budgetText: budget,
    distanceText: distance,
    reason,
    pros: pros.length ? pros : ["地点组合紧凑", "路线和时间已做可执行性校验"],
    cons: cons.length ? cons : ["部分营业或预约信息建议出发前再次确认"],
    metrics: [
      { label: "总时间", value: duration, hint: "含停留与交通" },
      { label: "预算", value: budget, hint: "按当前候选估算" },
      { label: "总距离", value: distance, hint: "含路线段" }
    ],
    timelinePreview: stops.slice(0, 4).map((stop) => `${stop.time} ${stop.title}`),
    summaryStops: stops.slice(0, 4),
    stops,
    mapMarkers: stops
      .filter((stop): stop is PlanStopView & { lat: number; lng: number } => stop.lat !== null && stop.lng !== null)
      .map((stop) => ({ id: stop.id, label: stop.label, title: stop.title, time: stop.time, lat: stop.lat, lng: stop.lng })),
    routeSummary: routeSummary(plan, stops, distance),
    routeSegments: plan.route?.segments ?? [],
    raw: plan
  };
}
