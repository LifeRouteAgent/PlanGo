import { AmapRouteCard } from "../../components/AmapRouteCard";
import { RouteBottomSheet } from "../../components/ui";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";

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
      />
      <RouteBottomSheet plan={plan} activeStop={activeStop} />
    </section>
  );
}
