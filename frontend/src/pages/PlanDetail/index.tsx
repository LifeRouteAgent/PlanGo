import { ArrowLeft, Clock3, MapPin, WalletCards } from "lucide-react";
import { useState } from "react";
import { AppleButton, EmptyState, SoftTag } from "../../components/ui";
import { uniqueHighlightTags, type PlanStopView, type PlanViewModel } from "../../utils/planViewModel";
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
  onPreferenceSubmit: (message: string) => void;
}

function compactHighlight(text: string): string {
  if (text.includes("距离") || text.includes("路线") || text.includes("交通")) return "距离合适";
  if (text.includes("预算") || text.includes("价格") || text.includes("花费")) return "预算友好";
  if (text.includes("时间") || text.includes("节奏") || text.includes("不赶")) return "节奏轻松";
  if (text.includes("室内") || text.includes("天气")) return "室内友好";
  if (text.includes("餐") || text.includes("吃") || text.includes("美食")) return "餐饮顺路";
  if (text.includes("朋友") || text.includes("对象") || text.includes("亲子")) return "人群匹配";
  return text.replace(/[，。；、,.!?！？\s]/g, "").slice(0, 6);
}

export function PlanDetail({ plan, onBack, onBackHome, onShare, onPreferenceSubmit }: PlanDetailProps) {
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

  const highlightTags = uniqueHighlightTags(
    plan.highlightTags.length ? plan.highlightTags : plan.pros.map(compactHighlight)
  );

  return (
    <section className="detail-page page-enter">
      <header className="page-header sticky-top detail-page-header">
        <AppleButton type="button" variant="ghost" size="sm" onClick={onBack} aria-label="返回方案总览">
          <ArrowLeft size={18} />
        </AppleButton>
        <div className="detail-title-block">
          <h2 style={{ fontSize: '23px', fontWeight: 600 }}>{plan.title}</h2>
        </div>
      </header>
        <div className="detail-metric-pills detail-metric-strip" aria-label="行程指标">
            {plan.durationText ? (
              <SoftTag tone="blue">
                <Clock3 size={15} />
                {plan.durationText}
              </SoftTag>
            ) : null}
            {plan.budgetText && !plan.budgetText.includes("待估") ? (
              <SoftTag tone="mint">
                <WalletCards size={15} />
                {plan.budgetText}
              </SoftTag>
            ) : null}
            {plan.distanceText && !plan.distanceText.includes("待估") ? (
              <SoftTag tone="blue">
                <MapPin size={15} />
                {plan.distanceText}
              </SoftTag>
            ) : null}
          </div>
      {modifyMessage && <div className="soft-notice">{modifyMessage}</div>}

      <div className="detail-layout-v2">
        <section className="detail-timeline-panel" aria-label="行程时间轴">
          <TimelineView
            stops={plan.stops}
            routeSegments={plan.routeSegments}
            selectedStopId={selectedStop?.id ?? null}
            onHoverStop={setActiveStopId}
            onOpenPlace={openPlace}
            onModify={openModify}
          />
        </section>

        <aside className="detail-insight-panel" aria-label="地图与方案分析">
          <MapView plan={plan} activeStopId={activeStopId} selectedStopId={selectedStop?.id ?? null} onSelectStop={openPlace} />

          <section className="detail-highlight-card">
            <h2>方案亮点</h2>
            <div className="detail-highlight-tags">
              {highlightTags.map((item) => (
                <SoftTag key={item} tone="mint" title={item}>
                  {item}
                </SoftTag>
              ))}
            </div>
          </section>

          <section className="detail-analysis-card">
            <h2>优缺点分析</h2>
            {plan.pros.length ? (
              <>
                <strong>优势</strong>
                <ul>
                  {plan.pros.slice(0, 3).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            ) : null}
            {plan.cons.length ? (
              <>
                <strong>注意事项</strong>
                <ul className="is-warning">
                  {plan.cons.slice(0, 3).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        </aside>
      </div>

      <BottomActionBar plan={plan} onBackHome={onBackHome} onShare={onShare} onModify={() => openModify()} />
      <PlaceDetailDrawer stop={selectedStop} onClose={() => setSelectedStop(null)} />
      <ModifyPreferenceDrawer
        open={modifyOpen}
        targetStop={modifyTarget}
        plan={plan}
        onClose={() => setModifyOpen(false)}
        onApply={(message) => {
          setModifyMessage(`已提交调整：${message}`);
          onPreferenceSubmit(message);
        }}
      />
    </section>
  );
}


