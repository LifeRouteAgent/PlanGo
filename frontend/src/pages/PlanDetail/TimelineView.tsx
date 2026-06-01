import { TimelineNode } from "../../components/ui";
import type { PlanStopView } from "../../utils/planViewModel";

interface TimelineViewProps {
  stops: PlanStopView[];
  selectedStopId: string | null;
  onHoverStop: (stopId: string | null) => void;
  onOpenPlace: (stop: PlanStopView) => void;
  onModify: (stop?: PlanStopView) => void;
}

export function TimelineView({ stops, selectedStopId, onHoverStop, onOpenPlace, onModify }: TimelineViewProps) {
  return (
    <section className="timeline-view" aria-label="行程时间轴">
      {stops.map((stop, index) => (
        <div key={stop.id} style={{ animationDelay: `${index * 0.04}s` }}>
          <TimelineNode
            stop={stop}
            selected={selectedStopId === stop.id}
            onHover={onHoverStop}
            onOpen={onOpenPlace}
            onModify={onModify}
          />
        </div>
      ))}
    </section>
  );
}
