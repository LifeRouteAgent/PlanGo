import {
  addPlanToCalendar,
  bookPlan,
  favoritePlan,
  getNavigation,
  getPlanAlternatives,
  getPlanDetails,
  getPlanMap,
  getRecommendations,
  savePlan,
  selectAlternative,
  sharePlan
} from "../api/streamClient";
import {
  ArrowRight,
  CalendarPlus,
  Car,
  Check,
  ChevronRight,
  Clock,
  Compass,
  Heart,
  Home,
  Leaf,
  MapPin,
  Navigation,
  Share2,
  Sparkles,
  Star,
  Ticket,
  Utensils,
  Users
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AmapRouteCard } from "../components/AmapRouteCard";
import { ChatAssistantPanel } from "../components/ChatAssistantPanel";
import { MapModal } from "../components/MapModal";
import { type DetailPayload, PlanDetailModal } from "../components/PlanDetailModal";
import { type TimelineEvent, usePlanStream } from "../hooks/usePlanStream";
import type { ChatHistoryItem, Plan, PlanAlternative, PlanStep } from "../types/agent";

interface PlannerWorkspaceProps {
  city: string;
  onCityChange: (city: string) => void;
  onPlanChange: (plan: Plan | null) => void;
  onTraceChange: (events: TimelineEvent[]) => void;
}

const nextActions = [
  { label: "导航", action: "Navigate", icon: Navigation, tone: "blue" },
  { label: "添加日历", action: "Add to Calendar", icon: CalendarPlus, tone: "purple" },
  { label: "分享方案", action: "Share Plan", icon: Share2, tone: "green" },
  { label: "预约餐厅", action: "Book Restaurant", icon: Utensils, tone: "orange" },
  { label: "保存方案", action: "Save Plan", icon: Heart, tone: "pink" }
] as const;

function formatDuration(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours}小时${rest}分钟`;
}

function getStep(plan: Plan, type: PlanStep["type"]) {
  return plan.steps.find((step) => step.type === type);
}

function getTags(plan: Plan) {
  return (plan.recommendation?.tags?.length
    ? plan.recommendation.tags
    : ["亲子友好", "低卡餐食", "室内活动"]
  ).slice(0, 3);
}

function peopleCount(plan: Plan) {
  return plan.actions[0]?.people_count || Math.max(1, plan.steps.length ? 3 : 1);
}

function routeTraffic(step: PlanStep) {
  const route = step.metadata.route as { duration_min?: number; distance_km?: number } | undefined;
  if (!route) {
    return step.detail?.traffic ?? "无需额外交通";
  }
  return `${route.distance_km ?? "-"} 公里，约 ${route.duration_min ?? "-"} 分钟`;
}

function detailFromAlternative(item: PlanAlternative): DetailPayload {
  return {
    type: "alternative",
    title: item.title,
    item
  };
}

export function PlannerWorkspace({ city, onPlanChange, onTraceChange }: PlannerWorkspaceProps) {
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailPayload | null>(null);
  const [isMapOpen, setIsMapOpen] = useState(false);
  const { isRunning, events, plan, assistantText, replacePlan, run, cancel } = usePlanStream();

  useEffect(() => {
    onPlanChange(plan);
  }, [onPlanChange, plan]);

  useEffect(() => {
    onTraceChange(events);
  }, [events, onTraceChange]);

  const activityStep = plan ? getStep(plan, "activity") : null;
  const travelStep = plan ? getStep(plan, "travel") : null;
  const mealStep = plan ? getStep(plan, "meal") : null;
  const visibleSteps = useMemo(() => plan?.steps ?? [], [plan]);
  const primaryStep = activityStep ?? mealStep ?? visibleSteps[0] ?? null;
  const tags = plan ? getTags(plan) : [];
  const visibleAlternatives = useMemo(() => plan?.alternatives?.slice(0, 3) ?? [], [plan]);

  async function runPlan(goal: string, history: ChatHistoryItem[]) {
    await run({
      goal,
      city,
      execute: true,
      fail_next_restaurant_booking: false,
      history
    });
  }

  async function requirePlanId() {
    if (!plan?.id) {
      setActionStatus("请先生成方案。");
      return null;
    }
    return plan.id;
  }

  async function handleNextAction(action: string) {
    const planId = await requirePlanId();
    if (!planId) {
      return;
    }

    try {
      if (action === "Save Plan") {
        const result = await savePlan(planId);
        replacePlan(result.plan);
        setActionStatus("方案已保存。");
        return;
      }
      if (action === "Share Plan") {
        const result = await sharePlan(planId);
        await navigator.clipboard?.writeText(result.share_message || result.share_url);
        setActionStatus("分享文案已复制。");
        return;
      }
      if (action === "Book Restaurant") {
        const result = await bookPlan(planId);
        replacePlan(result.plan);
        setActionStatus("餐厅预约已模拟确认。");
        return;
      }
      if (action === "Add to Calendar") {
        await addPlanToCalendar(planId);
        setActionStatus("日历事件已创建。");
        return;
      }
      if (action === "Navigate") {
        const route = await getNavigation(planId);
        setActionStatus(route.navigate_url ? "高德导航链接已准备好。" : "路线数据已准备好。");
      }
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleFilter(filter: string) {
    try {
      const result = await getRecommendations(filter, city);
      const label =
        {
          best_match: "最佳匹配",
          distance: "距离优先",
          family_friendly: "亲子友好",
          low_calorie: "低卡轻食"
        }[result.filter] ?? result.filter;
      setActionStatus(`${label}推荐已加载。`);
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleFavorite() {
    const planId = await requirePlanId();
    if (!planId) {
      return;
    }
    try {
      const result = await favoritePlan(planId);
      replacePlan(result.plan);
      setActionStatus("推荐已收藏。");
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleDetails(step?: PlanStep) {
    const planId = await requirePlanId();
    if (!planId || !plan) {
      return;
    }
    try {
      const result = await getPlanDetails(planId);
      replacePlan(result.details);
      const matchedStep = step
        ? result.details.steps.find((item) => item.title === step.title) ?? step
        : result.details.steps.find((item) => item.type === "activity") ?? activityStep ?? result.details.steps[0];
      if (matchedStep) {
        setDetail({ type: "step", title: matchedStep.title, item: matchedStep });
      }
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleFullMap() {
    const planId = await requirePlanId();
    if (!planId) {
      return;
    }
    try {
      await getPlanMap(planId);
      setIsMapOpen(true);
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleViewAllAlternatives() {
    const planId = await requirePlanId();
    if (!planId || !plan) {
      return;
    }
    try {
      const result = await getPlanAlternatives(planId);
      setDetail({ type: "alternatives", title: "更多备选方案", items: result.items });
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  async function handleAlternative(alternativeId?: string) {
    const planId = await requirePlanId();
    if (!planId || !alternativeId) {
      return;
    }
    try {
      const result = await selectAlternative(planId, alternativeId);
      replacePlan(result.plan);
      setActionStatus("已选择备选方案。");
      setDetail(null);
    } catch (error) {
      setActionStatus((error as Error).message);
    }
  }

  return (
    <div className="workspace-shell">
      <div className={`planner-page ${plan && visibleSteps.length > 0 ? "has-plan" : "is-empty"}`}>
        <section className="recommendation-heading">
          <div>
            <p className="eyebrow">为你推荐的最佳方案</p>
            <h1>
              {plan?.recommendation?.title ?? "先告诉我你的需求"} <Sparkles size={18} />
            </h1>
          </div>
          <div className="filter-row" aria-label="推荐筛选">
            <button type="button" onClick={() => void handleFilter("best_match")}>
              排序 <strong>最佳匹配</strong>
            </button>
            <button type="button" onClick={() => void handleFilter("distance")}>
              <MapPin size={16} /> 距离优先
            </button>
            <button type="button" onClick={() => void handleFilter("family_friendly")}>
              <Users size={16} /> 亲子友好
            </button>
            <button type="button" onClick={() => void handleFilter("low_calorie")}>
              <Leaf size={16} /> 低卡轻食
            </button>
          </div>
        </section>

        {(!plan || visibleSteps.length === 0) && (
          <section className="empty-planner">
            <p className="eyebrow">{plan ? "文本问答" : "从右侧对话开始"}</p>
            <h2>
              {plan
                ? "本轮是问答或说明类请求，回复已显示在右侧对话框。"
                : "告诉我人数、时间、预算和偏好，我会实时生成路线、行程和可执行操作。"}
            </h2>
            <p>
              {plan
                ? "如果你希望生成左侧行程，请输入包含时间、人数和活动偏好的本地生活规划需求。"
                : "当前只支持北京。生成前不会展示默认方案，推荐卡片、地图路线和底部操作栏都会在规划完成后出现。"}
            </p>
          </section>
        )}

        {plan && visibleSteps.length > 0 && primaryStep && (
            <>
              <section className="hero-grid">
                <article className="recommendation-card" onClick={() => void handleDetails()}>
                <div className="venue-visual">
                  <span className="best-match">最佳匹配</span>
                  <button
                    className="heart-button"
                    type="button"
                    aria-label="收藏推荐"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleFavorite();
                    }}
                  >
                    <Heart size={19} fill={plan.favorited ? "currentColor" : "none"} />
                  </button>
                  <div className="science-scene" aria-hidden="true">
                    <div className="planet planet-one" />
                    <div className="planet planet-two" />
                    <div className="child-shape" />
                    <div className="globe-shape" />
                  </div>
                </div>

                  <div className="recommendation-content">
                    <div className="title-line">
                    <h2>{plan.recommendation?.title ?? visibleSteps.map((step) => step.title).join(" + ")}</h2>
                      <span>
                        <Star size={18} fill="currentColor" /> {plan.recommendation?.rating ?? 4.8}
                    </span>
                  </div>
                  <div className="tag-cloud compact">
                    {tags.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                  <dl className="plan-stats">
                    <div>
                      <Clock size={17} />
                      <dt>总时长</dt>
                      <dd>{formatDuration(plan.total_duration_min)}</dd>
                    </div>
                    <div>
                      <Compass size={17} />
                      <dt>距离</dt>
                      <dd>{(plan.recommendation?.distance_km ?? 0).toFixed(1)} 公里</dd>
                    </div>
                    <div>
                      <Ticket size={17} />
                      <dt>人均费用</dt>
                      <dd>¥{Math.round(plan.total_cost / peopleCount(plan))}</dd>
                    </div>
                    <div>
                      <Users size={17} />
                      <dt>适合人数</dt>
                      <dd>{peopleCount(plan)} 人</dd>
                    </div>
                  </dl>
                  <div className="card-actions">
                    <button
                      className="secondary-action"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDetails();
                      }}
                    >
                      查看详情
                    </button>
                    <button className="primary-action" type="button" onClick={(event) => event.stopPropagation()}>
                      选择此方案 <ArrowRight size={17} />
                    </button>
                  </div>
                </div>
              </article>

              <AmapRouteCard plan={plan} onOpenFullMap={() => void handleFullMap()} />
            </section>

            <section className="details-grid">
              <article className="itinerary-card">
                <h2>行程安排</h2>
                <div className="itinerary-list">
                  <button className="itinerary-row home-row" type="button">
                    <Home size={18} />
                    <time>{plan.start_time}</time>
                    <span>从家出发</span>
                  </button>
                  {visibleSteps.map((step) => (
                      <button
                        className="itinerary-row"
                        type="button"
                        key={`${step.title}-${step.start_time}`}
                        onClick={() => void handleDetails(step)}
                      >
                      <span className={`step-icon is-${step.type}`}>
                        {step.type === "travel" ? <Car size={16} /> : step.type === "meal" ? <Utensils size={16} /> : <Sparkles size={16} />}
                      </span>
                      <time>
                        {step.start_time} - {step.end_time}
                      </time>
                      <div>
                        <strong>{step.title}</strong>
                        <p>{step.reason}</p>
                        <small>
                          <Car size={13} /> {routeTraffic(step)}
                        </small>
                      </div>
                    </button>
                  ))}
                  <button className="itinerary-row home-row" type="button">
                    <Home size={18} />
                    <time>{plan.end_time}</time>
                    <span>返回家中</span>
                  </button>
                </div>
              </article>

              <article className="insight-weather-card">
                <div>
                  <h2>方案亮点</h2>
                  <div className="reason-list">
                    {plan.rationale.slice(0, 5).map((reason) => (
                      <div className="reason-row" key={reason}>
                        <Check size={17} />
                        <span>{reason}</span>
                        <ChevronRight size={16} />
                      </div>
                    ))}
                  </div>
                </div>

                <div className="weather-card">
                  <div className="weather-icon">{plan.weather?.icon ?? "?"}</div>
                  <div>
                    <strong>
                      {plan.weather?.temperature_c === null || plan.weather?.temperature_c === undefined
                        ? "--"
                        : `${plan.weather.temperature_c}°C`}
                    </strong>
                    <span>{plan.weather?.condition ?? "天气未配置"}</span>
                  </div>
                  <small>{plan.weather?.summary ?? "请配置 AMAP_WEB_SERVICE_KEY 获取实时天气。"}</small>
                  <div className="hourly-weather">
                    {(plan.weather?.hourly ?? []).map((hour) => (
                      <div key={hour.time}>
                        <span>{hour.time}</span>
                        <strong>{hour.icon}</strong>
                        <small>{hour.temperature_c}°</small>
                      </div>
                    ))}
                  </div>
                </div>
              </article>

              <article className="alternatives-card">
                <div className="panel-title-row">
                  <h2>更多备选方案</h2>
                  <button type="button" onClick={() => void handleViewAllAlternatives()}>
                    查看全部
                  </button>
                </div>
                <div className="alternative-list">
                  {visibleAlternatives.map((item, index) => (
                    <button
                      className="alternative-row"
                      type="button"
                      key={item.id}
                      onClick={() => setDetail(detailFromAlternative(item))}
                    >
                      <div className={`alternative-thumb tone-${index}`} />
                      <div>
                        <strong>{item.title}</strong>
                        <span>
                          {item.rating} 星 | {item.distance_km.toFixed(1)} 公里 | {formatDuration(item.duration_min)}
                        </span>
                        <div>
                          {item.tags.map((tag) => (
                            <small key={tag}>{tag}</small>
                          ))}
                        </div>
                      </div>
                      <ChevronRight size={18} />
                    </button>
                  ))}
                </div>
              </article>
            </section>

            <section className="bottom-action-dock">
              <div>
                <h2>快捷操作</h2>
                {actionStatus && <span>{actionStatus}</span>}
              </div>
              <div className="action-bar">
                {nextActions.map((action) => {
                  const Icon = action.icon;
                  return (
                    <button
                      className="next-action-button"
                      data-tone={action.tone}
                      type="button"
                      key={action.label}
                      onClick={() => void handleNextAction(action.action)}
                    >
                      <Icon size={20} />
                      <span>{action.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          </>
        )}
      </div>

      <ChatAssistantPanel
        events={events}
        isRunning={isRunning}
        plan={plan}
        assistantText={assistantText}
        onSend={runPlan}
        onCancel={cancel}
      />
      <PlanDetailModal detail={detail} onClose={() => setDetail(null)} onSelectAlternative={(id) => void handleAlternative(id)} />
      <MapModal plan={isMapOpen ? plan : null} onClose={() => setIsMapOpen(false)} />
    </div>
  );
}
