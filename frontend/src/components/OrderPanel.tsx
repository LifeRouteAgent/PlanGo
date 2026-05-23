import { BadgeCheck, CircleX, RotateCcw } from "lucide-react";
import type { BookingAction, BookingStatus, Plan } from "../types/agent";

interface OrderPanelProps {
  plan: Plan | null;
}

const statusText: Record<BookingStatus, string> = {
  pending: "待执行",
  confirmed: "已确认",
  failed: "失败",
  compensated: "已补偿",
  skipped: "已跳过"
};

function statusIcon(action: BookingAction) {
  if (action.status === "confirmed") {
    return <BadgeCheck size={18} />;
  }
  if (action.status === "failed") {
    return <CircleX size={18} />;
  }
  return <RotateCcw size={18} />;
}

export function OrderPanel({ plan }: OrderPanelProps) {
  return (
    <section className="panel order-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">预订执行</p>
          <h2>预订与补偿</h2>
        </div>
      </div>

      {!plan && <p className="muted">执行动作会在方案生成后展示。</p>}

      {plan?.actions.map((action) => (
        <article className={`order-row status-${action.status}`} key={action.action_id}>
          <div className="order-icon">{statusIcon(action)}</div>
          <div>
            <strong>{action.target_name}</strong>
            <p>
              {action.action_type} / {action.scheduled_time}
              {action.order_id ? ` / ${action.order_id}` : ""}
            </p>
            {action.failure_reason && <p className="error-text">{action.failure_reason}</p>}
          </div>
          <span>{statusText[action.status]}</span>
        </article>
      ))}

      {plan?.risk_flags.map((risk) => (
        <div className="risk-callout" key={risk}>
          {risk}
        </div>
      ))}
    </section>
  );
}
