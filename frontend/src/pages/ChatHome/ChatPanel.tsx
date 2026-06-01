import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatBubble, ChatInput, GlassCard, LoadingSteps } from "../../components/ui";
import type { TimelineEvent } from "../../hooks/usePlanStream";
import { QuickChips } from "./QuickChips";

export interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  assistantDraft: string;
  events: TimelineEvent[];
  isRunning: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}

export function ChatPanel({ messages, assistantDraft, events, isRunning, onSubmit, onCancel }: ChatPanelProps) {
  const [draftPreference, setDraftPreference] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, assistantDraft, events]);

  const pickChip = (value: string) => {
    setDraftPreference((current) => (current ? `${current}，${value}` : value));
  };

  const submit = (value: string) => {
    const merged = draftPreference ? `${value}，偏好：${draftPreference}` : value;
    setDraftPreference("");
    onSubmit(merged);
  };

  return (
    <GlassCard as="section" className="chat-card" aria-label="PlanGo 对话框">
      <div className="chat-card-header">
        <div>
          <strong>PlanGo</strong>
          <span>本地生活 AI 规划助手</span>
        </div>
        <div className="chat-status-pill">
          <Sparkles size={15} />
          {isRunning ? "生成中" : "在线"}
        </div>
      </div>

      <div className="chat-card-scroll" ref={scrollRef}>
        {messages.map((message) => (
          <ChatBubble role={message.role} key={message.id}>
            <p>{message.content}</p>
          </ChatBubble>
        ))}

        {assistantDraft && (
          <ChatBubble role="assistant">
            <p>{assistantDraft}</p>
          </ChatBubble>
        )}

        {isRunning && <LoadingSteps events={events} />}
      </div>

      {draftPreference && (
        <div className="preference-draft">
          <span>已选择偏好：{draftPreference}</span>
          <button type="button" onClick={() => setDraftPreference("")}>
            清空
          </button>
        </div>
      )}

      <ChatInput running={isRunning} onSubmit={submit} onCancel={onCancel} />
      <QuickChips onPick={pickChip} />
    </GlassCard>
  );
}
