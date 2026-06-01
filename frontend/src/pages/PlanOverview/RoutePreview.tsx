import type { PlanViewModel } from "../../utils/planViewModel";

interface RoutePreviewProps {
  plan: PlanViewModel;
}

export function RoutePreview({ plan }: RoutePreviewProps) {
  const stops = plan.summaryStops;

  return (
    <div className="route-preview" aria-label="路线预览">
      <div className="route-preview-path">
        {stops.map((stop, index) => (
          <div className="route-preview-stop" key={stop.id} style={{ animationDelay: `${index * 0.04}s` }}>
            <span>{stop.label}</span>
            <small>{stop.title}</small>
          </div>
        ))}
      </div>
    </div>
  );
}
