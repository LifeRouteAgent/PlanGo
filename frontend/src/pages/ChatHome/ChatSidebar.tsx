import { Clock3, MapPin, MessageCirclePlus, SunMedium, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { ConversationRecord } from "../../utils/conversationStore";

interface ChatSidebarProps {
  conversationId: string;
  conversations: ConversationRecord[];
  onNewConversation: () => void;
  onLoadConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
}

interface HomeWeather {
  city: string;
  supported_scope: string;
  weather?: {
    temperature_c: number | null;
    condition: string;
    icon?: string;
  };
}

export function ChatSidebar({
  conversationId,
  conversations,
  onNewConversation,
  onLoadConversation,
  onDeleteConversation
}: ChatSidebarProps) {
  const visibleConversations = conversations.slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 10);
  const [weather, setWeather] = useState<HomeWeather | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationRecord | null>(null);

  useEffect(() => {
    let disposed = false;
    fetch("/api/home/weather")
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: HomeWeather | null) => {
        if (!disposed && payload) setWeather(payload);
      })
      .catch(() => {
        if (!disposed) setWeather(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  const confirmDelete = () => {
    if (!deleteTarget) return;
    onDeleteConversation(deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <aside className="chat-sidebar" aria-label="PlanGo 对话导航">
      <div className="chat-sidebar-brand">
        <span className="plango-logo-mark">P</span>
        <strong>PlanGo</strong>
      </div>

      <button type="button" className="sidebar-primary-action" onClick={onNewConversation} aria-label="新建聊天">
        <MessageCirclePlus size={20} />
        <span>新聊天</span>
      </button>

      <section className="sidebar-history" aria-label="历史对话">
        <div className="sidebar-section-title">
          <Clock3 size={15} />
          <span>最近</span>
        </div>
        <div className="sidebar-history-list">
          {visibleConversations.length ? (
            visibleConversations.map((record) => (
              <div
                className={`sidebar-history-row ${record.id === conversationId ? "is-active" : ""}`}
                key={record.id}
                role="button"
                tabIndex={0}
                onClick={() => onLoadConversation(record.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onLoadConversation(record.id);
                  }
                }}
              >
                <span className="sidebar-history-item">
                  <span>{record.title}</span>
                </span>
                <button
                  type="button"
                  className="sidebar-history-delete"
                  onClick={(event) => {
                    event.stopPropagation();
                    setDeleteTarget(record);
                  }}
                  aria-label={`删除对话：${record.title}`}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))
          ) : (
            <p className="sidebar-empty">暂无历史对话</p>
          )}
        </div>
      </section>

      <div className="sidebar-weather-card" aria-label="当前城市和天气">
        <div>
          <SunMedium size={16} />
          <strong>{weather?.city ?? "北京"}</strong>
        </div>
        <span>
          {weather?.weather?.condition ?? "天气加载中"}
          {weather?.weather?.temperature_c !== null && weather?.weather?.temperature_c !== undefined
            ? ` ${weather.weather.temperature_c}°C`
            : ""}
        </span>
        <small>
          <MapPin size={12} />
          {weather?.supported_scope ?? "目前仅支持北京"}
        </small>
      </div>

      {deleteTarget
        ? createPortal(
            <div className="confirm-dialog-backdrop" role="presentation" onMouseDown={() => setDeleteTarget(null)}>
              <section
                className="confirm-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="delete-conversation-title"
                onMouseDown={(event) => event.stopPropagation()}
              >
                <button type="button" className="confirm-dialog-close" onClick={() => setDeleteTarget(null)} aria-label="关闭">
                  <X size={16} />
                </button>
                <div className="confirm-dialog-icon">
                  <Trash2 size={20} />
                </div>
                <h3 id="delete-conversation-title">确定删除对话？</h3>
                <p>删除后，这条历史对话和对应的本地方案入口会从当前浏览器中移除。</p>
                <div className="confirm-dialog-actions">
                  <button type="button" className="confirm-dialog-secondary" onClick={() => setDeleteTarget(null)}>
                    取消
                  </button>
                  <button type="button" className="confirm-dialog-danger" onClick={confirmDelete}>
                    删除
                  </button>
                </div>
              </section>
            </div>,
            document.body
          )
        : null}
    </aside>
  );
}
