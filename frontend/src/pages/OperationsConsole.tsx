import { AlertTriangle, CheckCircle2, CircleDollarSign, TimerReset } from "lucide-react";
import type { BookingAction, BookingStatus, Plan } from "../types/agent";

interface OperationsConsoleProps {
  plan: Plan | null;
}

const statusLabel: Record<BookingStatus, string> = {
  pending: "待执行",
  confirmed: "已确认",
  failed: "失败",
  compensated: "已补偿",
  skipped: "已跳过"
};

const actionLabel: Record<string, string> = {
  reserve_ticket: "门票预订",
  reserve_table: "餐厅预订",
  navigate: "路线导航",
  calendar: "加入日历"
};

function countActions(actions: BookingAction[], status: BookingStatus) {
  return actions.filter((action) => action.status === status).length;
}

export function OperationsConsole({ plan }: OperationsConsoleProps) {
  const actions = plan?.actions ?? [];
  const confirmed = countActions(actions, "confirmed");
  const failed = countActions(actions, "failed");
  const compensated = countActions(actions, "compensated");
  const budget = plan ? `¥${Math.round(plan.total_cost)}` : "-";

  return (
    <div className="ops-page">
      <section className="page-heading">
        <p className="eyebrow">我的规划</p>
        <h1>执行状态与订单记录</h1>
        <p>查看最近一次规划生成后的预订、补偿、预算和风险提示。</p>
      </section>

      {!plan && (
        <section className="empty-panel">
          <TimerReset size={26} />
          <h2>还没有生成方案</h2>
          <p className="muted">请先在首页输入需求并完成一次规划，方案和执行动作会显示在这里。</p>
        </section>
      )}

      <section className="ops-metrics" aria-label="方案执行指标">
        <article className="ops-card">
          <CheckCircle2 size={22} />
          <span className="muted">已确认</span>
          <strong>{confirmed}</strong>
        </article>
        <article className="ops-card">
          <AlertTriangle size={22} />
          <span className="muted">失败</span>
          <strong>{failed}</strong>
        </article>
        <article className="ops-card">
          <TimerReset size={22} />
          <span className="muted">已补偿</span>
          <strong>{compensated}</strong>
        </article>
        <article className="ops-card">
          <CircleDollarSign size={22} />
          <span className="muted">预算</span>
          <strong>{budget}</strong>
        </article>
      </section>

      {plan && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">执行动作</p>
              <h2>
                {plan.start_time} - {plan.end_time}
              </h2>
            </div>
          </div>

          <div className="ledger-row muted" aria-hidden="true">
            <span>对象</span>
            <span>动作</span>
            <span>时间</span>
            <span>状态</span>
            <span>订单</span>
          </div>

          {actions.map((action) => (
            <article className={`ledger-row status-${action.status}`} key={action.action_id}>
              <strong>{action.target_name}</strong>
              <span>{actionLabel[action.action_type] ?? action.action_type}</span>
              <span>{action.scheduled_time}</span>
              <span>{statusLabel[action.status]}</span>
              <span>{action.order_id ?? "-"}</span>
              {action.failure_reason && <p className="error-text">{action.failure_reason}</p>}
            </article>
          ))}

          {actions.length === 0 && <p className="muted">当前方案没有需要执行的预订动作。</p>}
        </section>
      )}
    </div>
  );
}
