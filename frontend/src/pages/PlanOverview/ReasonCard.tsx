import { CheckCircle2, Info, Sparkles } from "lucide-react";
import { GlassCard } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface ReasonCardProps {
  plan: PlanViewModel | null;
}

export function ReasonCard({ plan }: ReasonCardProps) {
  if (!plan) {
    return null;
  }

  return (
    <GlassCard as="aside" className="reason-card">
      <div className="section-title">
        <Sparkles size={18} />
        <h2>优缺点</h2>
      </div>
      <p>{plan.reason}</p>
      <div className="reason-columns">
        <div>
          <strong>值得选它</strong>
          {plan.pros.map((item) => (
            <span key={item}>
              <CheckCircle2 size={15} />
              {item}
            </span>
          ))}
        </div>
        <div>
          <strong>需要确认</strong>
          {plan.cons.map((item) => (
            <span key={item}>
              <Info size={15} />
              {item}
            </span>
          ))}
        </div>
      </div>
    </GlassCard>
  );
}
