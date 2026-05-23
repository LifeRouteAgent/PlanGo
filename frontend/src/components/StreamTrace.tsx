import { CheckCircle2, CircleAlert, CircleDot, Loader2 } from "lucide-react";
import type { TimelineEvent } from "../hooks/usePlanStream";

interface StreamTraceProps {
  events: TimelineEvent[];
  isRunning: boolean;
}

function iconFor(level: TimelineEvent["level"]) {
  if (level === "success") {
    return <CheckCircle2 size={17} />;
  }
  if (level === "warning") {
    return <CircleAlert size={17} />;
  }
  if (level === "error") {
    return <CircleAlert size={17} />;
  }
  return <CircleDot size={17} />;
}

export function StreamTrace({ events, isRunning }: StreamTraceProps) {
  return (
    <section className="panel trace-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Agent Runtime</p>
          <h2>流式过程</h2>
        </div>
        {isRunning && <Loader2 className="spin" size={18} />}
      </div>

      <div className="trace-list">
        {events.length === 0 && <p className="muted">尚未开始。</p>}
        {events.map((event) => (
          <article className={`trace-item is-${event.level}`} key={event.id}>
            <div className="trace-icon">{iconFor(event.level)}</div>
            <div>
              <strong>{event.label}</strong>
              <p>{event.detail}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
