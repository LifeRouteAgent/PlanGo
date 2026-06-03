import { Building2, Flame, MapPin, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePlanStream } from "../../hooks/usePlanStream";
import type { Plan } from "../../types/agent";
import { AUTO_SUBMIT_EVENT, type AutoSubmitPayload } from "../../utils/autoSubmitEvent";
import type { StoredChatMessage } from "../../utils/conversationStore";
import { ChatPanelV2 } from "./ChatPanelV2";
import { WelcomeHero } from "./WelcomeHero";

interface HomeInspirationPoi {
  id: string;
  name: string;
  tag: string;
  tags: string[];
  image_url: string;
  duration_text: string;
}

type PendingSubmit = AutoSubmitPayload;

interface ChatHomeProps {
  conversationId: string;
  messages: StoredChatMessage[];
  hasPlan: boolean;
  onMessagesChange: (messages: StoredChatMessage[]) => void;
  onPlanReady: (plan: Plan) => void;
  onOpenPlans: () => void;
  onOpenDetail: () => void;
  onStreamComplete: (conversationId: string, messages: StoredChatMessage[], plan: Plan | null) => void;
  pendingSubmit?: PendingSubmit | null;
  onPendingSubmitConsumed?: () => void;
}

const quickStartItems = [
  { label: "附近推荐", prompt: "帮我推荐附近适合今天去的本地生活地点。", icon: MapPin },
  { label: "热门榜单", prompt: "帮我找几个北京热门的吃喝玩乐地点。", icon: Flame },
  { label: "今日特惠", prompt: "想找今天比较划算、预算友好的活动和餐厅。", icon: Sparkles },
  { label: "室内活动", prompt: "今天想安排室内活动，别太晒，路线轻松一点。", icon: Building2 }
];

export function ChatHome({
  conversationId,
  messages,
  hasPlan,
  onMessagesChange,
  onOpenPlans,
  onOpenDetail,
  onStreamComplete,
  pendingSubmit,
  onPendingSubmitConsumed
}: ChatHomeProps) {
  const { isRunning, events, plan, assistantText, run, cancel } = usePlanStream();
  const [streamConversationId, setStreamConversationId] = useState<string | null>(null);
  const streamBaseMessagesRef = useRef<StoredChatMessage[]>(messages);
  const streamRunIdRef = useRef("");
  const processedRunIdRef = useRef("");
  const processedPendingIdsRef = useRef<Set<string>>(new Set());
  const [inspirationPois, setInspirationPois] = useState<HomeInspirationPoi[]>([]);
  const [inspirationOffset, setInspirationOffset] = useState(0);
  const isCurrentConversationRunning = isRunning && streamConversationId === conversationId;

  useEffect(() => {
    let disposed = false;
    fetch("/api/home/inspirations?limit=12")
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { items?: HomeInspirationPoi[] } | null) => {
        if (!disposed) setInspirationPois(payload?.items ?? []);
      })
      .catch(() => {
        if (!disposed) setInspirationPois([]);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (isRunning || !streamConversationId || processedRunIdRef.current === streamRunIdRef.current) {
      return;
    }
    if (!assistantText && !plan) {
      return;
    }

    processedRunIdRef.current = streamRunIdRef.current;
    const completedMessages = assistantText
      ? [
          ...streamBaseMessagesRef.current,
          {
            id: crypto.randomUUID(),
            role: "assistant" as const,
            content: assistantText
          }
        ]
      : streamBaseMessagesRef.current;

    window.setTimeout(() => {
      onStreamComplete(streamConversationId, completedMessages, plan);
      setStreamConversationId(null);
    }, 240);
  }, [assistantText, isRunning, onStreamComplete, plan, streamConversationId]);

  const submit = useCallback(
    (goal: string) => {
      const trimmedGoal = goal.trim();
      if (!trimmedGoal || isRunning) return;

      const nextMessages: StoredChatMessage[] = [
        ...messages,
        {
          id: crypto.randomUUID(),
          role: "user",
          content: trimmedGoal
        }
      ];

      onMessagesChange(nextMessages);
      streamBaseMessagesRef.current = nextMessages;
      streamRunIdRef.current = crypto.randomUUID();
      processedRunIdRef.current = "";
      setStreamConversationId(conversationId);

      void run({
        goal: trimmedGoal,
        city: "beijing",
        execute: false,
        fail_next_restaurant_booking: false,
        session_id: conversationId,
        history: nextMessages.map((message) => ({
          role: message.role === "assistant" ? "assistant" : "user",
          content: message.content
        }))
      });
    },
    [conversationId, isRunning, messages, onMessagesChange, run]
  );

  const submitPending = useCallback(
    (pending: PendingSubmit | null | undefined) => {
      if (!pending || processedPendingIdsRef.current.has(pending.id)) return;
      processedPendingIdsRef.current.add(pending.id);
      onPendingSubmitConsumed?.();
      submit(pending.text);
    },
    [onPendingSubmitConsumed, submit]
  );

  useEffect(() => {
    if (!isRunning) submitPending(pendingSubmit);
  }, [pendingSubmit?.id, isRunning, submitPending]);

  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<PendingSubmit>).detail;
      if (!isRunning) submitPending(detail);
    };
    window.addEventListener(AUTO_SUBMIT_EVENT, listener);
    return () => window.removeEventListener(AUTO_SUBMIT_EVENT, listener);
  }, [isRunning, submitPending]);

  const visibleInspirations = inspirationPois.length
    ? Array.from(
        { length: Math.min(4, inspirationPois.length) },
        (_, index) => inspirationPois[(inspirationOffset + index) % inspirationPois.length]
      )
    : [];

  return (
    <div className="chat-home">
      <div className="chat-home-main">
        <div className="chat-home-inner">
          <WelcomeHero />
          <div className="chat-workbench">
            <ChatPanelV2
              messages={messages}
              assistantDraft={isCurrentConversationRunning ? assistantText : ""}
              events={isCurrentConversationRunning ? events : []}
              isRunning={isCurrentConversationRunning}
              hasPlan={hasPlan}
              onSubmit={submit}
              onCancel={() => {
                cancel();
                setStreamConversationId(null);
              }}
              onOpenPlans={onOpenPlans}
              onOpenDetail={onOpenDetail}
            />
            <aside className="home-inspiration-panel" aria-label="灵感推荐">
              <section>
                <strong>快速开始</strong>
                <div className="inspiration-actions">
                  {quickStartItems.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button type="button" key={item.label} onClick={() => submit(item.prompt)}>
                        <span className="inspiration-action-icon">
                          <Icon size={22} />
                        </span>
                        <span style={{ fontSize: "14px" }}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </section>
              <section>
                <div className="inspiration-section-head">
                  <strong>灵感推荐</strong>
                  <button type="button" onClick={() => setInspirationOffset((value) => value + 3)} aria-label="换一批灵感推荐">
                    <RefreshCw size={16} />
                  </button>
                </div>
                {visibleInspirations.map((poi) => (
                  <button
                    type="button"
                    className="inspiration-poi-card"
                    key={`${poi.id}-${poi.name}`}
                    onClick={() => submit(`我想去 ${poi.name}，帮我搭配一个本地生活方案。`)}
                  >
                    <img src={poi.image_url} alt={poi.name} loading="lazy" />
                    <span>
                      <strong>{poi.name}</strong>
                      <small>
                        {poi.tag || poi.tags[0] || "本地生活"} · {poi.duration_text}
                      </small>
                    </span>
                  </button>
                ))}
              </section>
            </aside>
          </div>
        </div>
      </div>
    </div>
  );
}
