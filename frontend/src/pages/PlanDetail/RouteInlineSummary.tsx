import { ArrowRightLeft, Clock3, MapPin } from "lucide-react";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";

interface RouteInlineSummaryProps {
  plan: PlanViewModel;
  activeStop?: PlanStopView | null;
}

function normalizeMode(mode: string): string {
  const value = mode.toLowerCase();
  if (value.includes("drive") || value.includes("car") || value.includes("驾车") || value.includes("自驾")) return "驾车";
  if (value.includes("taxi") || value.includes("打车")) return "打车";
  if (value.includes("walk") || value.includes("步行")) return "步行";
  if (value.includes("bus") || value.includes("transit") || value.includes("metro") || value.includes("地铁") || value.includes("公交")) return "公共交通";
  return mode;
}

export function RouteInlineSummary({ plan, activeStop }: RouteInlineSummaryProps) {
  const totalRouteMinutes = plan.raw.route?.segments?.reduce((sum, segment) => sum + (segment.duration_min ?? 0), 0) ?? 0;
  const modes = Array.from(
    new Set((plan.raw.route?.segments ?? []).map((segment) => segment.transport_mode).filter(Boolean).map((mode) => normalizeMode(String(mode))))
  );
  const routeLabel = plan.stops.length ? plan.stops.map((stop) => stop.label).join(" → ") : "";

  return (
    <aside className="route-bottom-sheet route-inline-summary">
      <div>
        <strong>{activeStop ? activeStop.title : routeLabel}</strong>
        <span>{activeStop ? activeStop.time : "按当前路线估算"}</span>
      </div>
      <dl>
        <div>
          <MapPin size={15} />
          <dt>总距离</dt>
          <dd>{plan.distanceText}</dd>
        </div>
        <div>
          <Clock3 size={15} />
          <dt>交通时间</dt>
          <dd>{totalRouteMinutes ? `约 ${totalRouteMinutes} 分钟` : "待确认"}</dd>
        </div>
        <div>
          <ArrowRightLeft size={15} />
          <dt>方式</dt>
          <dd>{modes.length ? modes.join(" / ") : "待确认"}</dd>
        </div>
      </dl>
    </aside>
  );
}
