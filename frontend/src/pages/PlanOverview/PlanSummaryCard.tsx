import { ArrowRight, CheckCircle2, Sparkles, XCircle } from "lucide-react";
import { AppleButton, GlassCard, SoftTag } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";
import { RoutePreview } from "./RoutePreview";

interface PlanSummaryCardProps {
  plan: PlanViewModel;
  selected?: boolean;
  onOpenDetail: (plan: PlanViewModel) => void;
}

export function PlanSummaryCard({ plan, selected = false, onOpenDetail }: PlanSummaryCardProps) {
  return (
    <GlassCard as="article" className="plan-summary-card" hoverable selected={selected}>
      <div className="plan-summary-top">
        <div className="plan-card-badges">
          <SoftTag tone="blue" tabIndex={-1}>
            <Sparkles size={14} />
            {plan.badge}
          </SoftTag>
          <SoftTag tone="mint" tabIndex={-1}>
            {plan.styleTag}
          </SoftTag>
        </div>
        <h2>{plan.title}</h2>
        <p>{plan.reason}</p>
      </div>

      <RoutePreview plan={plan} />

      <dl className="metric-grid">
        {plan.metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
            <small>{metric.hint}</small>
          </div>
        ))}
      </dl>

      <div className="plan-fit-row">
        <span>适合人群</span>
        <strong>{plan.audience}</strong>
      </div>

      <div className="plan-pros-cons">
        <div>
          <strong>
            <CheckCircle2 size={15} />
            优点
          </strong>
          {plan.pros.slice(0, 2).map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
        <div>
          <strong>
            <XCircle size={15} />
            注意
          </strong>
          {plan.cons.slice(0, 2).map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </div>

      <div className="mini-timeline">
        {plan.timelinePreview.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>

      <AppleButton type="button" full onClick={() => onOpenDetail(plan)}>
        查看完整行程
        <ArrowRight size={18} className="button-arrow" />
      </AppleButton>
    </GlassCard>
  );
}
