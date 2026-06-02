import { AmapRouteCard } from "../../components/AmapRouteCard";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";
import { RouteInlineSummary } from "./RouteInlineSummary";

interface MapViewProps {
  plan: PlanViewModel;
  activeStopId: string | null;
  selectedStopId: string | null;
  onSelectStop: (stop: PlanStopView) => void;
}

export function MapView({ plan, activeStopId, selectedStopId, onSelectStop }: MapViewProps) {
  const activeStop = plan.stops.find((stop) => stop.id === selectedStopId || stop.id === activeStopId) ?? null;

  return (
    <section className="map-view">
      <AmapRouteCard
        plan={plan.raw}
        large
        activeStopId={activeStopId ?? selectedStopId ?? undefined}
        onStopSelect={(stopId) => {
          const stop = plan.stops.find((item) => item.id === stopId);
            if (stop) onSelectStop(stop);
        }}
        footer={<RouteInlineSummary plan={plan} activeStop={activeStop} />}
      />
    </section>
  );
}
