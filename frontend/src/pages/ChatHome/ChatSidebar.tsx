import { Clock3, MessageCirclePlus } from "lucide-react";
import type { ConversationRecord } from "../../utils/conversationStore";

interface ChatSidebarProps {
  conversationId: string;
  conversations: ConversationRecord[];
  onNewConversation: () => void;
  onLoadConversation: (conversationId: string) => void;
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

export function ChatSidebar({ conversationId, conversations, onNewConversation, onLoadConversation }: ChatSidebarProps) {
  const visibleConversations = conversations.slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 10);

  return (
    <aside className="chat-sidebar" aria-label="PlanGo 对话导航">
      <div className="chat-sidebar-brand">
        <span className="plango-logo-mark">P</span>
        <strong>PlanGo</strong>
      </div>

      <button type="button" className="sidebar-primary-action" onClick={onNewConversation}>
        <MessageCirclePlus size={20} />
        <span>新对话</span>
      </button>

      <section className="sidebar-history" aria-label="历史对话">
        <div className="sidebar-section-title">
          <Clock3 size={15} />
          <span>历史对话</span>
        </div>
        <div className="sidebar-history-list">
          {visibleConversations.length ? (
            visibleConversations.map((record) => (
              <button
                type="button"
                className={`sidebar-history-item ${record.id === conversationId ? "is-active" : ""}`}
                key={record.id}
                onClick={() => onLoadConversation(record.id)}
              >
                <span>{record.title}</span>
                <small>
                  {formatConversationTime(record.updatedAt)}
                  {record.plan ? <em>有方案</em> : null}
                </small>
              </button>
            ))
          ) : (
            <p className="sidebar-empty">暂无历史对话</p>
          )}
        </div>
      </section>
    </aside>
  );
}
