import { Download, Home, Share2 } from "lucide-react";
import { exportPlanPdf } from "../../api/streamClient";
import { AppleButton, GlassCard } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface ActionBarProps {
  selectedPlan: PlanViewModel | null;
  onBackHome: () => void;
  onShare: () => void;
}

export function ActionBar({ selectedPlan, onBackHome, onShare }: ActionBarProps) {
  const exportPdf = () => {
    if (!selectedPlan) return;
    void exportPlanPdf(selectedPlan.raw);
  };

  return (
    <GlassCard className="overview-action-bar">
      <AppleButton type="button" variant="ghost" onClick={onBackHome}>
        <Home size={17} />
        继续对话调整
      </AppleButton>
      <AppleButton type="button" variant="secondary" onClick={exportPdf} disabled={!selectedPlan}>
        <Download size={17} />
        导出 PDF
      </AppleButton>
      <AppleButton type="button" onClick={onShare} disabled={!selectedPlan}>
        <Share2 size={17} />
        分享方案
      </AppleButton>
    </GlassCard>
  );
}
