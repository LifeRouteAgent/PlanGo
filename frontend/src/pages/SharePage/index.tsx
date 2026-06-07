import { ArrowLeft, Check, Copy, Home, MessageCircle, Share2 } from "lucide-react";
import { useState } from "react";
import { AppleButton, EmptyState, GlassCard, SoftTag } from "../../components/ui";
import type { PlanViewModel } from "../../utils/planViewModel";

interface SharePageProps {
  plan: PlanViewModel | null;
  feedbackMessage: string;
  onFeedback: (message: string) => void;
  onBack: () => void;
  onBackHome: () => void;
}

const voteOptions = ["想去这条", "路线太远", "预算再低点", "换成室内", "晚餐清淡点"];

export function SharePage({ plan, feedbackMessage, onFeedback, onBack, onBackHome }: SharePageProps) {
  const [copied, setCopied] = useState(false);

  if (!plan) {
    return (
      <EmptyState
        title="暂无可分享方案"
        description="生成方案后，PlanGo 会在这里展示适合发给家人或朋友的行程卡片。"
        actionLabel="返回首页"
        onAction={onBackHome}
      />
    );
  }

  const copyShareText = async () => {
    const stops = plan.stops.slice(0, 5).map((stop) => `${stop.label} ${stop.title}`).join(" / ");
    const text = `${plan.title}\n${plan.reason}\n${stops}`;
    await navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <section className="share-page page-enter">
      <header className="page-header sticky-top">
        <AppleButton type="button" variant="ghost" size="sm" onClick={onBack} aria-label="返回">
          <ArrowLeft size={18} />
        </AppleButton>
        <div>
          <span>分享给家人和朋友</span>
          <h2>PlanGo 行程投票卡</h2>
        </div>
      </header>

      <GlassCard as="article" className="share-card">
        <SoftTag tone="blue">
          <Share2 size={14} />
          PlanGo Share
        </SoftTag>
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
        <AppleButton type="button" variant="secondary" onClick={() => void copyShareText()}>
          {copied ? <Check size={16} /> : <Copy size={16} />}
          {copied ? "已复制" : "复制分享文案"}
        </AppleButton>
      </GlassCard>

      <GlassCard as="section" className="feedback-panel">
        <div className="section-title">
          <MessageCircle size={18} />
          <h2>朋友投票</h2>
        </div>
        <div className="feedback-buttons">
          {voteOptions.map((item) => (
            <SoftTag type="button" key={item} selected={feedbackMessage === item} onClick={() => onFeedback(item)}>
              {item}
            </SoftTag>
          ))}
        </div>
        {feedbackMessage && (
          <p className="feedback-done">
            <Check size={16} />
            已记录投票：{feedbackMessage}
          </p>
        )}
      </GlassCard>

      <AppleButton type="button" variant="ghost" className="share-home-action centered" onClick={onBackHome}>
        <Home size={17} />
        回到 PlanGo 首页
      </AppleButton>
    </section>
  );
}
