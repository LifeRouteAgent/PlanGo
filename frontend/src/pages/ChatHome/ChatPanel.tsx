import { Clock3, History, MapPinned, Plus, Route } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AppleButton, ChatBubble, ChatInput, GlassCard, LoadingSteps, MarkdownMessage, SoftTag } from "../../components/ui";
import type { TimelineEvent } from "../../hooks/usePlanStream";
import type { ConversationRecord, StoredChatMessage } from "../../utils/conversationStore";
import { QuickChips } from "./QuickChips";

interface ChatPanelProps {
  conversationId: string;
  conversations: ConversationRecord[];
  messages: StoredChatMessage[];
  assistantDraft: string;
  events: TimelineEvent[];
  isRunning: boolean;
  hasPlan: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  onOpenPlans: () => void;
  onOpenDetail: () => void;
  onNewConversation: () => void;
  onLoadConversation: (conversationId: string) => void;
}

export function ChatPanel({
  conversationId,
  conversations,
  messages,
  assistantDraft,
  events,
  isRunning,
  hasPlan,
  onSubmit,
  onCancel,
  onOpenPlans,
  onOpenDetail,
  onNewConversation,
  onLoadConversation
}: ChatPanelProps) {
  const [draftPreference, setDraftPreference] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, assistantDraft, events]);

  const visibleConversations = useMemo(
    () => conversations.slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 8),
    [conversations]
  );

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
        </div>
        <div className="chat-header-actions">
          <AppleButton size="sm" variant="ghost" onClick={onNewConversation}>
            <Plus size={15} />
            新对话
          </AppleButton>
          <AppleButton size="sm" variant="ghost" onClick={() => setHistoryOpen((open) => !open)}>
            <History size={15} />
            历史
          </AppleButton>
          <AppleButton size="sm" variant="secondary" disabled={!hasPlan} onClick={onOpenPlans}>
            <Route size={15} />
            方案
          </AppleButton>
          <AppleButton size="sm" variant="secondary" disabled={!hasPlan} onClick={onOpenDetail}>
            <MapPinned size={15} />
            详情
          </AppleButton>
        </div>
      </div>

      {historyOpen && (
        <div className="conversation-history-panel" aria-label="历史对话">
          <div className="conversation-history-head">
            <strong>历史对话</strong>
            <span>选择后会恢复聊天记录和对应方案</span>
          </div>
          {visibleConversations.length ? (
            <div className="conversation-history-list">
              {visibleConversations.map((record) => (
                <button
                  type="button"
                  className={`conversation-history-item ${record.id === conversationId ? "is-active" : ""}`}
                  key={record.id}
                  onClick={() => {
                    setHistoryOpen(false);
                    onLoadConversation(record.id);
                  }}
                >
                  <span>{record.title}</span>
                  <small>
                    <Clock3 size={12} />
                    {formatConversationTime(record.updatedAt)}
                  </small>
                </button>
              ))}
            </div>
          ) : (
            <p className="conversation-history-empty">暂无历史对话</p>
          )}
        </div>
      )}

      <div className="chat-card-scroll" ref={scrollRef}>
        {messages.map((message) => (
          <ChatBubble role={message.role} key={message.id}>
            <MarkdownMessage content={message.content} />
          </ChatBubble>
        ))}

        {assistantDraft && (
          <ChatBubble role="assistant">
            <MarkdownMessage content={assistantDraft} />
          </ChatBubble>
        )}

        {isRunning && <LoadingSteps events={events} isRunning={isRunning} />}
      </div>

      {draftPreference && (
        <div className="preference-draft">
          <span>已选择偏好：{draftPreference}</span>
          <SoftTag tone="blue" onClick={() => setDraftPreference("")}>
            清空
          </SoftTag>
        </div>
      )}

      <ChatInput running={isRunning} onSubmit={submit} onCancel={onCancel} />
      <QuickChips onPick={pickChip} />
    </GlassCard>
  );
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}
