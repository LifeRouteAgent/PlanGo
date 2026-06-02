import { ArrowLeft } from "lucide-react";
import { AppleButton, EmptyState } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";
import { PlanChoiceCard } from "./PlanChoiceCard";

interface PlanOverviewProps {
  plans: PlanViewModel[];
  onBackHome: () => void;
  onOpenDetail: (plan: PlanViewModel) => void;
  onShare: (plan: PlanViewModel) => void;
}

export function PlanOverview({ plans, onBackHome, onOpenDetail, onShare }: PlanOverviewProps) {
  void onShare;

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
          {/* <span>PlanGo 为你生成了 {plans.length} 个不同地点组合</span> */}
          <h2>选择一条最想出发的路线</h2>
        </div>
      </header>

      <div className="overview-layout overview-layout-single">
        <div className="plan-grid route-choice-grid">
          {plans.map((plan, index) => (
            <div key={plan.id} style={{ animationDelay: `${index * 0.05}s` }}>
              <PlanChoiceCard order={index} plan={plan} onOpenDetail={onOpenDetail} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
