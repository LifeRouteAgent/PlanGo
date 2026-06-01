import type { Plan, PlanStep, StreamEvent, StreamRequest, WeatherInfo } from "../types/agent";

type StreamHandler = (event: StreamEvent) => void;

const planCache = new Map<string, Plan>();

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asString(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function asNumber(value: unknown, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function parseSseFrame(frame: string): { event: string; data: unknown } | null {
  let eventName = "message";
  let data = "";

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    }
    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }

  if (!data) {
    return null;
  }

  return {
    event: eventName,
    data: JSON.parse(data) as unknown
  };
}

function scenarioFromIntent(intentType: unknown): Plan["scenario"] {
  const value = String(intentType ?? "");
  if (value.includes("family")) {
    return "family";
  }
  if (value.includes("couple")) {
    return "couple";
  }
  if (value.includes("friend") || value.includes("party")) {
    return "friends";
  }
  return "unknown";
}

function stepTypeFromSlot(slotType: string, category: string): PlanStep["type"] {
  const value = `${slotType} ${category}`;
  if (value.includes("restaurant") || value.includes("餐")) {
    return "meal";
  }
  if (value.includes("travel") || value.includes("route")) {
    return "travel";
  }
  return "activity";
}

function getItemPoi(item: Record<string, unknown>) {
  return {
    ...asRecord(item.poi),
    ...item
  };
}

function imageFromPoi(poi: Record<string, unknown>) {
  const images = asArray<string>(poi.images);
  return asString(poi.image_url ?? poi.cover_image ?? images[0], "");
}

function buildStep(item: Record<string, unknown>, index: number): PlanStep {
  const poi = getItemPoi(item);
  const slotType = asString(item.slot_type ?? item.type ?? poi.category, "activity");
  const category = asString(poi.category ?? item.category, "activity");
  const title = asString(poi.name ?? item.name ?? item.title, `第 ${index + 1} 站`);
  const lat = asNumber(poi.lat ?? poi.latitude, 39.9042);
  const lng = asNumber(poi.lon ?? poi.lng ?? poi.longitude, 116.4074);
  const reason = asString(
    item.recommendation_reason ?? poi.recommendation_reason ?? item.reason,
    "符合本次时间、距离和偏好约束。"
  );
  const cost = asNumber(item.estimated_cost ?? poi.avg_price ?? poi.price, 0);

  return {
    type: stepTypeFromSlot(slotType, category),
    title,
    start_time: asString(item.start_time, "--:--"),
    end_time: asString(item.end_time, "--:--"),
    location: { name: title, lat, lng, address: asString(poi.address, "地址待确认") },
    target_id: asString(poi.id ?? item.id, `${index}`),
    reason,
    cost,
    booking_required: Boolean(item.reservation_required ?? poi.reservation_required),
    metadata: { slot_type: slotType, category, rating: poi.rating, raw: item },
    detail: {
      image_url: imageFromPoi(poi) || null,
      tags: asArray<string>(poi.tags).slice(0, 5),
      description: reason,
      traffic: asString(item.travel_summary, "交通耗时由高德路线或系统估算。"),
      cost,
      address: asString(poi.address, "地址待确认")
    }
  };
}

function mergeItemsWithTimeline(source: Record<string, unknown>) {
  const items = asArray<Record<string, unknown>>(source.items);
  const timeline = asArray<Record<string, unknown>>(source.timeline);
  if (!timeline.length) return items;
  const itemById = new Map(items.map((item) => [asString(item.id ?? item.target_id), item]));
  return timeline.map((slot, index) => {
    const id = asString(slot.item_id ?? slot.poi_id ?? slot.target_id ?? slot.id);
    const matched = itemById.get(id) ?? items[index] ?? {};
    return { ...matched, ...slot };
  });
}

function buildRouteSegments(routeSegments: Record<string, unknown>[]) {
  return routeSegments.map((segment, index) => {
    const polyline = asArray<Record<string, unknown>>(segment.polyline).map((point) => ({
      lat: asNumber(point.lat),
      lng: asNumber(point.lng)
    }));
    return {
      type: "travel" as const,
      title: asString(segment.transport_mode, `第 ${index + 1} 段交通`),
      color: index % 2 ? "#7EDFC0" : "#5BA8FF",
      polyline,
      distance_km: asNumber(segment.distance_km, 0),
      duration_min: asNumber(segment.duration_minutes, 0),
      transport_mode: asString(segment.transport_mode, "")
    };
  });
}

function buildWeather(source: Record<string, unknown>, response: Record<string, unknown>): WeatherInfo {
  const weather = asRecord(source.weather ?? response.weather);
  if (Object.keys(weather).length) {
    return {
      temperature_c: weather.temperature_c === null || weather.temperature_c === undefined ? null : asNumber(weather.temperature_c),
      condition: asString(weather.condition, "天气未知"),
      icon: asString(weather.icon, "🌤️"),
      summary: asString(weather.summary, "已接入高德实时天气。"),
      source: asString(weather.source, "amap") as WeatherInfo["source"],
      hourly: asArray(weather.hourly),
      message: asString(weather.message, "")
    };
  }
  return { temperature_c: null, condition: "天气未配置", icon: "🌤️", summary: "暂未获取到高德实时天气。", source: "unconfigured", hourly: [] };
}

function buildPlanFromSource(
  source: Record<string, unknown>,
  response: Record<string, unknown>,
  rankedPlans: Record<string, unknown>[],
  includeAlternatives: boolean
): Plan {
  const steps = mergeItemsWithTimeline(source).map(buildStep);
  const firstStep = steps[0];
  const lastStep = steps[steps.length - 1];
  const planId = asString(source.plan_id ?? source.id, crypto.randomUUID());
  const title = asString(source.title, "本地生活推荐方案");
  const fitSummary = asString(asRecord(source.fit_summary).summary ?? source.recommendation_reason ?? response.response_text, "根据偏好、时间、距离和预算生成。");
  const tags = asArray<string>(source.tags).length ? asArray<string>(source.tags) : ["本地生活", "路线可执行", "智能规划"];
  const routeSegments = asArray<Record<string, unknown>>(source.route_segments);
  const routeSegmentViews = buildRouteSegments(routeSegments);
  const hasOriginSegment = routeSegments.length === steps.length;
  steps.forEach((step, index) => {
    const segmentIndex = hasOriginSegment ? index : index - 1;
    const segment = segmentIndex >= 0 ? routeSegments[segmentIndex] : undefined;
    if (!segment) return;
    const distance = asNumber(segment.distance_km, 0);
    const duration = asNumber(segment.duration_minutes, 0);
    const mode = asString(segment.transport_mode, "交通");
    step.metadata.route = { distance_km: distance, duration_min: duration, mode };
    if (step.detail) {
      step.detail.traffic = `${mode}，${distance.toFixed(1)} 公里，约 ${duration} 分钟`;
    }
  });
  const routePolyline = routeSegmentViews.flatMap((segment) => segment.polyline);
  const totalCost = asNumber(source.estimated_budget ?? source.total_cost, steps.reduce((sum, step) => sum + step.cost, 0));

  const plan: Plan = {
    id: planId,
    trace_id: asString(response.trace_id),
    run_id: asString(response.run_id),
    session_id: asString(response.session_id),
    scenario: scenarioFromIntent(response.intent_type),
    start_time: firstStep?.start_time ?? "--:--",
    end_time: lastStep?.end_time ?? "--:--",
    total_duration_min: asNumber(source.total_duration_minutes ?? source.duration_minutes, 0),
    total_cost: totalCost,
    steps,
    actions: steps.filter((step) => step.type === "meal" || step.booking_required).map((step, index) => ({
      action_id: `${planId}-action-${index}`,
      action_type: step.type === "meal" ? "restaurant_booking" : "ticket_or_reservation",
      target_id: step.target_id ?? `${index}`,
      target_name: step.title,
      scheduled_time: step.start_time,
      people_count: asNumber(asRecord(response.constraints).people_count, 2),
      status: "pending",
      order_id: null,
      failure_reason: null
    })),
    rationale: [fitSummary, ...asArray<string>(source.pros).slice(0, 2), ...steps.map((step) => step.reason).slice(0, 2)].filter(Boolean),
    share_message: asString(response.response_text, `${title}：${fitSummary}`),
    risk_flags: asArray<Record<string, unknown>>(response.errors).map((item) => asString(item.message ?? item.code, "存在待确认风险")),
    city: { code: "beijing", name: "北京" },
    recommendation: {
      title,
      rating: asNumber(source.score ?? source.plan_score, 4.7),
      distance_km: asNumber(source.total_distance_km ?? routeSegments[0]?.distance_km, 0),
      tags,
      cover_image: firstStep?.detail?.image_url ?? null
    },
    route: {
      provider: routeSegments.some((segment) => asString(segment.source).startsWith("amap")) ? "高德地图" : "LifeRouteAgent",
      source: asString(routeSegments[0]?.source, "langgraph"),
      polyline: routePolyline.length ? routePolyline : steps.map((step) => step.location).filter(Boolean).map((location) => ({ lat: location!.lat, lng: location!.lng })),
      segments: routeSegmentViews,
      stops: steps.map((step, index) => ({ order: index + 1, title: step.title, start_time: step.start_time, end_time: step.end_time, location: step.location })),
      navigate_url: null
    },
    alternatives: includeAlternatives ? rankedPlans.slice(1, 4).map((item, index) => {
      const altPlan = buildPlanFromSource(item, response, [], false);
      return {
        id: asString(item.plan_id ?? item.id, `alt-${index}`),
        title: asString(item.title, `备选方案 ${index + 1}`),
        rating: asNumber(item.score ?? item.plan_score, 4.5),
        distance_km: asNumber(item.total_distance_km, 0),
        duration_min: asNumber(item.total_duration_minutes, 0),
        total_cost: asNumber(item.estimated_budget, 0),
        tags: asArray<string>(item.tags).slice(0, 4),
        description: asString(asRecord(item.fit_summary).summary ?? item.recommendation_reason, "可作为当前方案的备选。"),
        steps: altPlan.steps,
        route: altPlan.route,
        recommendation_reason: asString(item.recommendation_reason, ""),
        pros: asArray<string>(item.pros),
        cons: asArray<string>(item.cons)
      };
    }) : [],
    weather: buildWeather(source, response),
    details: { steps, alternatives: [] }
  };

  planCache.set(planId, plan);
  return plan;
}

function buildPlanFromLifeRouteResponse(payload: unknown): Plan {
  const response = asRecord(payload);
  const selected = asRecord(response.selected_plan);
  const rankedPlans = asArray<Record<string, unknown>>(response.ranked_plans);
  const source = Object.keys(selected).length ? selected : asRecord(rankedPlans[0]);
  return buildPlanFromSource(source, response, rankedPlans, true);
}
function normalizeSseEvent(raw: { event: string; data: unknown }): StreamEvent | null {
  if (raw.event === "final") {
    const response = asRecord(raw.data);
    const hasPlan = asArray(response.ranked_plans).length > 0 || Object.keys(asRecord(response.selected_plan)).length > 0;
    const plan = hasPlan ? buildPlanFromLifeRouteResponse(raw.data) : null;
    const trace = asArray<string>(asRecord(raw.data).logs);
    return { event: "done", data: { plan, trace } };
  }

  if (raw.event === "done") {
    return null;
  }

  if (raw.event === "status") {
    return { event: "status", data: { message: asString(asRecord(raw.data).message, "系统正在处理。") } };
  }

  if (raw.event === "progress") {
    return { event: "progress", data: { message: asString(asRecord(raw.data).message, "规划仍在运行。") } };
  }

  if (raw.event === "agent_thinking") {
    const data = asRecord(raw.data);
    return {
      event: "status",
      data: {
        message: `${asString(data.title, "Agent 节点")}：${asString(data.message, "正在处理。")}`
      }
    };
  }

  if (raw.event === "error") {
    return { event: "error", data: { message: asString(asRecord(raw.data).message, "请求失败") } };
  }

  return raw as StreamEvent;
}

async function ensureOk(response: Response, message: string) {
  if (!response.ok) {
    throw new Error(`${message}：${response.status}`);
  }
}

export async function streamPlan(
  request: StreamRequest,
  onEvent: StreamHandler,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch("/api/plan-stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...request,
      user_query: request.goal,
      user_profile: {
        city: request.city
      }
    }),
    signal
  });

  if (!response.ok || !response.body) {
    throw new Error(`流式接口请求失败：${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const parsed = parseSseFrame(frame);
      if (parsed) {
        const normalized = normalizeSseEvent(parsed);
        if (normalized) {
          onEvent(normalized);
        }
      }
    }
  }
}

async function postPlanAction<T>(planId: string, action: string): Promise<T> {
  const cachedPlan = planCache.get(planId);
  const response = await fetch(`/api/plans/${planId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });

  if (response.ok) {
    return response.json() as Promise<T>;
  }

  if (!cachedPlan) {
    await ensureOk(response, "方案操作失败");
  }

  const nextPlan = cachedPlan ? { ...cachedPlan } : ({} as Plan);
  if (action === "save") {
    nextPlan.saved = true;
    return { plan: nextPlan, saved: true } as T;
  }
  if (action === "favorite") {
    nextPlan.favorited = true;
    return { plan: nextPlan, favorited: true } as T;
  }
  if (action === "book") {
    nextPlan.actions = nextPlan.actions.map((item) => ({
      ...item,
      status: "confirmed",
      order_id: item.order_id ?? `MOCK-${Date.now()}`
    }));
    return { plan: nextPlan, actions: nextPlan.actions } as T;
  }
  if (action === "share") {
    return {
      share_id: `share-${planId}`,
      share_url: window.location.href,
      share_message: nextPlan.share_message ?? "这是我生成的本地生活方案。"
    } as T;
  }
  if (action === "calendar") {
    return {
      calendar_event_id: `calendar-${planId}`,
      title: nextPlan.recommendation?.title ?? "本地生活方案",
      start_time: nextPlan.start_time,
      end_time: nextPlan.end_time,
      status: "created"
    } as T;
  }
  if (action === "navigate") {
    return nextPlan.route as T;
  }
  return { plan: nextPlan } as T;
}

export function savePlan(planId: string) {
  return postPlanAction<{ plan: Plan; saved: boolean }>(planId, "save");
}

export function sharePlan(planId: string) {
  return postPlanAction<{ share_id: string; share_url: string; share_message: string }>(
    planId,
    "share"
  );
}

export function bookPlan(planId: string) {
  return postPlanAction<{ plan: Plan; actions: Plan["actions"] }>(planId, "book");
}

export function addPlanToCalendar(planId: string) {
  return postPlanAction<{
    calendar_event_id: string;
    title: string;
    start_time: string;
    end_time: string;
    status: string;
  }>(planId, "calendar");
}

export function getNavigation(planId: string) {
  return postPlanAction<NonNullable<Plan["route"]>>(planId, "navigate");
}

export function favoritePlan(planId: string) {
  return postPlanAction<{ plan: Plan; favorited: boolean }>(planId, "favorite");
}

export async function exportPlanPdf(plan: Plan) {
  const response = await fetch("/export/plan/pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan,
      session_id: plan.session_id,
      trace_id: plan.trace_id
    })
  });
  await ensureOk(response, "PDF 导出失败");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${plan.recommendation?.title || "PlanGo行程方案"}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return { ok: true };
}

export async function createSession() {
  return { session_id: crypto.randomUUID(), city: "beijing" };
}

export async function startVoiceInput() {
  return { status: "mock", message: "当前浏览器语音输入使用占位能力。" };
}

export async function getCities() {
  const response = await fetch("/api/cities");
  await ensureOk(response, "城市列表加载失败");
  const result = (await response.json()) as { cities: Array<{ code: string; name: string; enabled?: boolean }> };
  return {
    cities: result.cities.map((item) => ({ ...item, enabled: item.enabled ?? true }))
  };
}

export async function getWeather(_city = "beijing") {
  return {
    weather: {
      temperature_c: null,
      condition: "未配置",
      icon: "☁️",
      summary: "天气接口未启用，方案会优先使用室内/室外偏好和用户输入约束。",
      source: "unconfigured",
      hourly: []
    } satisfies WeatherInfo
  };
}

export async function getRecommendations(filter: string, _city = "beijing") {
  return {
    filter,
    items: [],
    alternatives: [],
    available_filters: ["best_match", "distance", "family_friendly", "low_calorie"]
  };
}

export async function getPlanDetails(planId: string) {
  const details = planCache.get(planId);
  if (!details) {
    throw new Error("方案详情加载失败：当前页面没有缓存该方案");
  }
  return { details };
}

export async function getPlanMap(planId: string) {
  const plan = planCache.get(planId);
  if (!plan?.route) {
    throw new Error("地图数据加载失败：当前方案没有路线");
  }
  return { map: plan.route };
}

export async function getPlanAlternatives(planId: string) {
  const plan = planCache.get(planId);
  return { items: plan?.alternatives ?? [] };
}

export async function runQuickAction(action: string) {
  const presets: Record<string, { title: string; prompt: string; filters: Record<string, unknown> }> = {
    new: { title: "新建规划", prompt: "", filters: {} },
    indoor: { title: "室内优先", prompt: "今天太热，帮我安排室内为主的周末活动", filters: { indoor: true } },
    budget: { title: "省钱方案", prompt: "帮我安排一个预算更低的本地生活方案", filters: { budget: "low" } },
    family: { title: "亲子半日", prompt: "周末带孩子玩半天，别太远，安排亲子活动和吃饭", filters: { scene: "family" } }
  };
  return { action: presets[action] ?? presets.new };
}

export async function getUserSection(section: "favorites" | "history" | "calendar" | "profile") {
  if (section === "profile") {
    const response = await fetch("/api/user/profile");
    await ensureOk(response, "用户栏目加载失败");
    return response.json() as Promise<unknown>;
  }
  return { section, items: [] };
}

export async function selectAlternative(planId: string, alternativeId: string) {
  const plan = planCache.get(planId);
  if (!plan) {
    throw new Error("备选方案选择失败：当前页面没有缓存该方案");
  }
  const selected = plan.alternatives?.find((item) => item.id === alternativeId);
  return { plan, selected_alternative: selected };
}

