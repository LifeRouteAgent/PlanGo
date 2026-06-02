import { ArrowRight, MapPinned, Route } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AppleButton, ChatBubble, ChatInput, GlassCard, LoadingSteps, MarkdownMessage } from "../../components/ui";
import type { TimelineEvent } from "../../hooks/usePlanStream";
import type { StoredChatMessage } from "../../utils/conversationStore";
import { QuickChips } from "./QuickChips";

interface ChatPanelV2Props {
  messages: StoredChatMessage[];
  assistantDraft: string;
  events: TimelineEvent[];
  isRunning: boolean;
  hasPlan: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  onOpenPlans: () => void;
  onOpenDetail: () => void;
}

export function ChatPanelV2({
  messages,
  assistantDraft,
  events,
  isRunning,
  hasPlan,
  onSubmit,
  onCancel,
  onOpenPlans,
  onOpenDetail
}: ChatPanelV2Props) {
  const [draftPreference, setDraftPreference] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, assistantDraft, events, hasPlan]);

  const pickChip = (chip: string) => {
    setDraftPreference((current) => {
      if (!current) return chip;
      if (current.includes(chip)) return current;
      return `${current}，${chip}`;
    });
  };

  const submit = (value: string) => {
    const merged = draftPreference ? `${value}，偏好：${draftPreference}` : value;
    setDraftPreference("");
    onSubmit(merged);
  };

  return (
    <GlassCard className="chat-card chat-card-hero" as="section">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <ChatBubble role="assistant">
            <strong>Hi，我是 PlanGo 👋</strong>
            <p>今天想和谁一起出行？把人数、时间、预算和偏好告诉我，我会帮你整理成可执行的本地生活方案。</p>
          </ChatBubble>
        ) : null}

        {messages.map((message) => (
          <ChatBubble key={message.id} role={message.role}>
            {message.role === "assistant" ? <MarkdownMessage content={message.content} /> : <p>{message.content}</p>}
          </ChatBubble>
        ))}

        {assistantDraft ? (
          <ChatBubble role="assistant">
            <MarkdownMessage content={assistantDraft} />
          </ChatBubble>
        ) : null}

        {isRunning ? <LoadingSteps events={events} /> : null}

        {hasPlan && !isRunning ? (
          <article className="chat-plan-link-card">
            <div className="chat-plan-link-copy">
              <span>已生成路线</span>
              <strong>查看 PlanGo 为你准备的 3 个方案</strong>
              <small>可以先比较地点组合，再进入完整行程查看地图、路线和每一站详情。</small>
            </div>
            <div className="chat-plan-link-actions">
              <AppleButton type="button" size="sm" onClick={onOpenPlans}>
                查看方案
                <ArrowRight size={15} className="button-arrow" />
              </AppleButton>
              <AppleButton type="button" size="sm" variant="secondary" onClick={onOpenDetail}>
                <MapPinned size={15} />
                看详情
              </AppleButton>
            </div>
          </article>
        ) : null}
      </div>

      {draftPreference ? (
        <div className="draft-preference">
          <Route size={15} />
          <span>已选择偏好：{draftPreference}</span>
        </div>
      ) : null}

      <ChatInput
        running={isRunning}
        onCancel={onCancel}
        onSubmit={submit}
        placeholder="想去哪儿？和谁一起？预算和时间大概多少？"
      />
      <QuickChips onPick={pickChip} />
    </GlassCard>
  );
}
