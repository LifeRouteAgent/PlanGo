import { ArrowLeft } from "lucide-react";
import { useMemo, useState } from "react";
import { AppleButton, EmptyState } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";
import { ActionBar } from "./ActionBar";
import { PlanSummaryCard } from "./PlanSummaryCard";
import { ReasonCard } from "./ReasonCard";

interface PlanOverviewProps {
  plans: PlanViewModel[];
  onBackHome: () => void;
  onOpenDetail: (plan: PlanViewModel) => void;
  onShare: (plan: PlanViewModel) => void;
}

export function PlanOverview({ plans, onBackHome, onOpenDetail, onShare }: PlanOverviewProps) {
  const [selectedId, setSelectedId] = useState(plans[0]?.id ?? "");
  const selectedPlan = useMemo(() => plans.find((plan) => plan.id === selectedId) ?? plans[0] ?? null, [plans, selectedId]);

  if (!plans.length) {
    return (
      <EmptyState
        title="还没有生成方案"
        description="回到首页输入你的本地生活需求，PlanGo 会为你生成可比较、可查看路线的方案。"
        actionLabel="返回首页"
        onAction={onBackHome}
      />
    );
  }

  return (
    <section className="plan-page page-enter">
      <header className="page-header sticky-top">
        <AppleButton type="button" variant="ghost" size="sm" onClick={onBackHome} aria-label="返回首页">
          <ArrowLeft size={18} />
        </AppleButton>
        <div>
          <span>PlanGo 为你生成了 {plans.length} 个方案</span>
          <h1>选择一个最合适的周末安排</h1>
        </div>
      </header>

      <div className="overview-layout">
        <div className="plan-grid">
          {plans.map((plan, index) => (
            <div key={plan.id} style={{ animationDelay: `${index * 0.05}s` }} onMouseEnter={() => setSelectedId(plan.id)}>
              <PlanSummaryCard selected={selectedPlan?.id === plan.id} plan={plan} onOpenDetail={onOpenDetail} />
            </div>
          ))}
        </div>
        <div className="overview-side">
          <ReasonCard plan={selectedPlan} />
          <ActionBar selectedPlan={selectedPlan} onBackHome={onBackHome} onShare={() => selectedPlan && onShare(selectedPlan)} />
        </div>
      </div>
    </section>
  );
}
