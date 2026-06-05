import { AlertCircle, Check, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { TimelineEvent } from "../../hooks/usePlanStream";

interface LoadingStepsProps {
  events: TimelineEvent[];
  isRunning?: boolean;
}

function statusIcon(event: TimelineEvent) {
  if (event.status === "success") return <Check size={14} />;
  if (event.status === "warning" || event.status === "failed") return <AlertCircle size={14} />;
  if (event.status === "running") return <Loader2 size={14} className="spin" />;
  return null;
}

export function LoadingSteps({ events, isRunning = false }: LoadingStepsProps) {
  const [collapsed, setCollapsed] = useState(false);
  const hasCompleted = !isRunning && events.some((event) => event.status === "success" && event.phase === "done");

  useEffect(() => {
    if (isRunning) {
      setCollapsed(false);
      return;
    }
    if (hasCompleted) {
      setCollapsed(true);
    }
  }, [hasCompleted, isRunning]);

  if (!events.length) return null;

  return (
    <section className={`loading-steps ${collapsed ? "is-collapsed" : ""}`} aria-live="polite">
      <button type="button" className="loading-steps-title" onClick={() => setCollapsed((value) => !value)}>
        {isRunning && !collapsed ? <Loader2 size={18} className="spin" /> : null}
        <span>{collapsed ? "规划过程已完成" : "规划过程"}</span>
        {collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
      </button>
      {!collapsed ? (
        <div className="loading-steps-timeline">
          {events.map((event) => (
            <article className={`loading-step-row is-${event.status}`} key={event.id}>
              <span className="loading-step-dot">{statusIcon(event)}</span>
              <div>
                <strong>{event.label}</strong>
                <p>{event.detail}</p>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
