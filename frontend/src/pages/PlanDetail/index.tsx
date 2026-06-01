import { ArrowLeft, Map, Route, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { AppleButton, EmptyState, SegmentedControl } from "../../components/ui";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";
import { BottomActionBar } from "./BottomActionBar";
import { MapView } from "./MapView";
import { ModifyPreferenceDrawer } from "./ModifyPreferenceDrawer";
import { PlaceDetailDrawer } from "./PlaceDetailDrawer";
import { TimelineView } from "./TimelineView";

interface PlanDetailProps {
  plan: PlanViewModel | null;
  onBack: () => void;
  onBackHome: () => void;
  onShare: () => void;
  onPlanUpdate: (plan: PlanViewModel | null) => void;
}

export function PlanDetail({ plan, onBack, onBackHome, onShare }: PlanDetailProps) {
  const [tab, setTab] = useState<"timeline" | "map">("timeline");
  const [activeStopId, setActiveStopId] = useState<string | null>(null);
  const [selectedStop, setSelectedStop] = useState<PlanStopView | null>(null);
  const [modifyOpen, setModifyOpen] = useState(false);
  const [modifyTarget, setModifyTarget] = useState<PlanStopView | null>(null);
  const [modifyMessage, setModifyMessage] = useState("");

  if (!plan) {
    return (
      <EmptyState
        title="没有可查看的行程"
        description="请先从首页生成方案，再进入详情页查看时间轴和地图。"
        actionLabel="返回首页"
        onAction={onBackHome}
      />
    );
  }

  const openModify = (stop?: PlanStopView) => {
    setModifyTarget(stop ?? null);
    setModifyOpen(true);
  };

  const openPlace = (stop: PlanStopView) => {
    setSelectedStop(stop);
    setActiveStopId(stop.id);
  };
  const previewStop = selectedStop ?? plan.stops.find((stop) => stop.id === activeStopId) ?? plan.stops[0] ?? null;

  return (
    <section className="detail-page page-enter">
      <header className="page-header detail-header sticky-top">
        <AppleButton type="button" variant="ghost" size="sm" onClick={onBack} aria-label="返回方案总览">
          <ArrowLeft size={18} />
        </AppleButton>
        <div>
          <span>{plan.audience} · {plan.durationText} · {plan.budgetText}</span>
          <h1>{plan.title}</h1>
        </div>
        <AppleButton type="button" variant="secondary" onClick={() => openModify()}>
          <SlidersHorizontal size={17} />
          调整偏好
        </AppleButton>
      </header>

      {modifyMessage && <div className="soft-notice">{modifyMessage}</div>}

      <div className="detail-shell">
        <aside className="detail-left">
          <SegmentedControl
            label="行程详情视图"
            value={tab}
            onChange={setTab}
            options={[
              { value: "timeline", label: "时间轴", icon: <Route size={16} /> },
              { value: "map", label: "地图", icon: <Map size={16} /> }
            ]}
          />
          <TimelineView
            stops={plan.stops}
            selectedStopId={selectedStop?.id ?? null}
            onHoverStop={setActiveStopId}
            onOpenPlace={openPlace}
            onModify={openModify}
          />
        </aside>
        <div className="detail-right">
          {tab === "timeline" ? (
            <div className="stop-preview-card">
              <span>当前地点</span>
              <h2>{previewStop?.title ?? "选择时间轴节点查看详情"}</h2>
              <p>{previewStop?.reason ?? "悬停或点击左侧时间轴节点，右侧会同步显示地点摘要。"}</p>
              <div className="stop-preview-meta">
                <strong>{previewStop?.time ?? "时间待定"}</strong>
                <small>{previewStop?.traffic ?? plan.routeSummary.transportModesText}</small>
              </div>
            </div>
          ) : (
            <MapView plan={plan} activeStopId={activeStopId} selectedStopId={selectedStop?.id ?? null} onSelectStop={openPlace} />
          )}
        </div>
      </div>

      <BottomActionBar plan={plan} onBackHome={onBackHome} onShare={onShare} onModify={() => openModify()} />
      <PlaceDetailDrawer stop={selectedStop} onClose={() => setSelectedStop(null)} />
      <ModifyPreferenceDrawer
        open={modifyOpen}
        targetStop={modifyTarget}
        plan={plan}
        onClose={() => setModifyOpen(false)}
        onApply={(message) => setModifyMessage(`已记录偏好：${message}。当前版本先在页面内保留，后续可接入局部重规划。`)}
      />
    </section>
  );
}
