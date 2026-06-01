import { ArrowLeft, Check, Home, MessageCircle } from "lucide-react";
import { AppleButton, EmptyState, GlassCard, SoftTag } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface SharePageProps {
  plan: PlanViewModel | null;
  feedbackMessage: string;
  onFeedback: (message: string) => void;
  onBack: () => void;
  onBackHome: () => void;
}

const feedbacks = ["想轻松一点", "晚餐清淡一点", "别太远", "预算再低点", "换成室内"];

export function SharePage({ plan, feedbackMessage, onFeedback, onBack, onBackHome }: SharePageProps) {
  if (!plan) {
    return (
      <EmptyState
        title="暂无可分享方案"
        description="生成方案后，PlanGo 会在这里展示适合发给家人或朋友的极简行程卡片。"
        actionLabel="返回首页"
        onAction={onBackHome}
      />
    );
  }

  return (
    <section className="share-page page-enter">
      <header className="page-header sticky-top">
        <AppleButton type="button" variant="ghost" size="sm" onClick={onBack} aria-label="返回">
          <ArrowLeft size={18} />
        </AppleButton>
        <div>
          <span>分享给家人和朋友</span>
          <h1>PlanGo 极简行程卡</h1>
        </div>
      </header>

      <GlassCard as="article" className="share-card">
        <SoftTag tone="blue">PlanGo Share</SoftTag>
        <h2>{plan.title}</h2>
        <p>{plan.reason}</p>
        <dl>
          {plan.metrics.map((metric) => (
            <div key={metric.label}>
              <dt>{metric.label}</dt>
              <dd>{metric.value}</dd>
            </div>
          ))}
        </dl>
        <div className="share-stops">
          {plan.stops.slice(0, 5).map((stop) => (
            <span key={stop.id}>
              <strong>{stop.label}</strong>
              {stop.title}
            </span>
          ))}
        </div>
      </GlassCard>

      <GlassCard as="section" className="feedback-panel">
        <div className="section-title">
          <MessageCircle size={18} />
          <h2>朋友反馈</h2>
        </div>
        <div className="feedback-buttons">
          {feedbacks.map((item) => (
            <SoftTag type="button" key={item} selected={feedbackMessage === item} onClick={() => onFeedback(item)}>
              {item}
            </SoftTag>
          ))}
        </div>
        {feedbackMessage && (
          <p className="feedback-done">
            <Check size={16} />
            已记录反馈：{feedbackMessage}
          </p>
        )}
      </GlassCard>

      <AppleButton type="button" variant="ghost" className="centered" onClick={onBackHome}>
        <Home size={17} />
        回到 PlanGo 首页
      </AppleButton>
    </section>
  );
}
