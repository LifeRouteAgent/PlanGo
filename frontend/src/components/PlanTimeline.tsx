import { Clock, MapPin, Ticket } from "lucide-react";
import type { Plan } from "../types/agent";

interface PlanTimelineProps {
  plan: Plan | null;
}

export function PlanTimeline({ plan }: PlanTimelineProps) {
  if (!plan) {
    return (
      <section className="empty-panel">
        <Clock size={24} />
        <h2>等待生成时间线</h2>
        <p>Agent 会在流式规划过程中逐步生成活动、餐厅、路线和执行动作。</p>
      </section>
    );
  }

  return (
    <section className="panel timeline-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">可执行时间线</p>
          <h2>{plan.start_time} - {plan.end_time}</h2>
        </div>
        <div className="metric">
          <span>预算</span>
          <strong>¥{Math.round(plan.total_cost)}</strong>
        </div>
      </div>

      <div className="timeline-list">
        {plan.steps.map((step, index) => (
          <article className="timeline-item" key={`${step.title}-${index}`}>
            <div className="timeline-time">
              <strong>{step.start_time}</strong>
              <span>{step.end_time}</span>
            </div>
            <div className="timeline-dot" />
            <div className="timeline-body">
              <div className="timeline-title">
                <span>{step.title}</span>
                {step.booking_required && (
                  <span className="small-badge">
                    <Ticket size={13} />
                    需预约
                  </span>
                )}
              </div>
              <p>{step.reason}</p>
              {step.location && (
                <div className="location-line">
                  <MapPin size={14} />
                  <span>{step.location.address || step.location.name}</span>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
