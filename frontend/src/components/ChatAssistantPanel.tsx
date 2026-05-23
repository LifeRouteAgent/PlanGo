import { ChevronDown, ChevronRight, SendHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { TimelineEvent } from "../hooks/usePlanStream";
import type { ChatHistoryItem, Plan } from "../types/agent";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  status?: "streaming" | "done" | "error";
  collapsible?: boolean;
}

interface ChatAssistantPanelProps {
  events: TimelineEvent[];
  isRunning: boolean;
  plan: Plan | null;
  onSend: (goal: string, history: ChatHistoryItem[]) => Promise<void>;
  onCancel: () => void;
}

function nowTime() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date());
}

function toHistory(messages: ChatMessage[]): ChatHistoryItem[] {
  return messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .slice(-8)
    .map((message) => ({ role: message.role as "user" | "assistant", content: message.content }));
}

export function ChatAssistantPanel({ events, isRunning, plan, onSend, onCancel }: ChatAssistantPanelProps) {
  const [input, setInput] = useState("");
  const [progressCollapsed, setProgressCollapsed] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "你好，我是生活规划助手。告诉我出行人数、时间、预算和偏好，我会帮你生成路线、行程和可执行操作。",
      timestamp: nowTime(),
      status: "done"
    }
  ]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const doneEventRef = useRef<string | null>(null);

  const progressEvents = useMemo(
    () =>
      events.filter((event) =>
        ["understanding", "searching", "routing", "validating", "executing", "done", "error"].includes(event.phase)
      ),
    [events]
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, progressEvents, progressCollapsed]);

  useEffect(() => {
    const done = events.find((event) => event.phase === "done");
    if (!done || doneEventRef.current === done.id) {
      return;
    }
    doneEventRef.current = done.id;
    setProgressCollapsed(true);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content: plan?.recommendation?.title
          ? `已为你生成「${plan.recommendation.title}」。你可以查看详情、打开完整地图，或直接使用底部操作栏继续导航、预约和保存。`
          : "规划已完成，你可以查看推荐方案、地图路线、行程安排和后续操作。",
        timestamp: nowTime(),
        status: "done"
      }
    ]);
  }, [events, plan]);

  async function submit() {
    const goal = input.trim();
    if (!goal || isRunning) {
      return;
    }
    const history = toHistory(messages);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: goal,
        timestamp: nowTime(),
        status: "done"
      }
    ]);
    setProgressCollapsed(false);
    setInput("");
    await onSend(goal, history);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <aside className="chat-panel">
      <header className="chat-header">
        <div>
          <strong>生活规划助手</strong>
          <span>{isRunning ? "规划中" : "在线"}</span>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((message) => (
          <article className={`chat-message is-${message.role}`} key={message.id}>
            <p>{message.content}</p>
            <time>{message.timestamp}</time>
          </article>
        ))}

        {progressEvents.length > 0 && (
          <section className="progress-message">
            <button type="button" onClick={() => setProgressCollapsed((value) => !value)}>
              <span>{progressCollapsed ? "规划过程已完成" : "规划中..."}</span>
              {progressCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
            </button>
            {!progressCollapsed && (
              <div className="progress-list">
                {progressEvents.map((event) => (
                  <div className={`progress-row is-${event.level}`} key={event.id}>
                    <span />
                    <div>
                      <strong>{event.label}</strong>
                      <p>{event.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      <footer className="chat-input-area">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入你的需求..."
          rows={2}
        />
        <button
          type="button"
          className="chat-send"
          onClick={isRunning ? onCancel : () => void submit()}
          disabled={!isRunning && !input.trim()}
        >
          {isRunning ? "停止" : <SendHorizontal size={20} />}
        </button>
      </footer>
    </aside>
  );
}
