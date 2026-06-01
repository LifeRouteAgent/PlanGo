import { CalendarPlus, Download, Home, PlayCircle, Share2, SlidersHorizontal } from "lucide-react";
import { addPlanToCalendar, bookPlan, exportPlanPdf } from "../../api/streamClient";
import type { PlanViewModel } from "../../utils/planViewModel";

interface BottomActionBarProps {
  plan: PlanViewModel;
  onBackHome: () => void;
  onShare: () => void;
  onModify: () => void;
}

export function BottomActionBar({ plan, onBackHome, onShare, onModify }: BottomActionBarProps) {
  return (
    <div className="bottom-action-bar">
      <button type="button" onClick={onBackHome}>
        <Home size={17} />
        继续对话
      </button>
      <button type="button" onClick={onModify}>
        <SlidersHorizontal size={17} />
        调整偏好
      </button>
      <button type="button" onClick={() => void exportPlanPdf(plan.raw)}>
        <Download size={17} />
        导出 PDF
      </button>
      <button type="button" onClick={() => void addPlanToCalendar(plan.id)}>
        <CalendarPlus size={17} />
        加入日历
      </button>
      <button type="button" onClick={onShare}>
        <Share2 size={17} />
        分享
      </button>
      <button type="button" className="primary" onClick={() => void bookPlan(plan.id)}>
        <PlayCircle size={17} />
        执行方案
      </button>
    </div>
  );
}
