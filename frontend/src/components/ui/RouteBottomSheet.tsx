import { ArrowRightLeft, Clock3, MapPin } from "lucide-react";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";

interface RouteBottomSheetProps {
  plan: PlanViewModel;
  activeStop?: PlanStopView | null;
}

export function RouteBottomSheet({ plan, activeStop }: RouteBottomSheetProps) {
  const totalRouteMinutes = plan.raw.route?.segments?.reduce((sum, segment) => sum + (segment.duration_min ?? 0), 0) ?? 0;
  const modes = Array.from(new Set(plan.raw.route?.segments?.map((segment) => segment.transport_mode).filter(Boolean) ?? []));

  return (
    <aside className="route-bottom-sheet">
      <div>
        <strong>{activeStop ? activeStop.title : "路线摘要"}</strong>
        <span>{activeStop ? activeStop.time : plan.stops.map((stop) => stop.label).join(" → ")}</span>
      </div>
      <dl>
        <div>
          <MapPin size={15} />
          <dt>总距离</dt>
          <dd>{plan.distanceText}</dd>
        </div>
        <div>
          <Clock3 size={15} />
          <dt>交通</dt>
          <dd>{totalRouteMinutes ? `约 ${totalRouteMinutes} 分钟` : "待确认"}</dd>
        </div>
        <div>
          <ArrowRightLeft size={15} />
          <dt>方式</dt>
          <dd>{modes.length ? modes.join(" / ") : "步行 / 打车"}</dd>
        </div>
      </dl>
    </aside>
  );
}
