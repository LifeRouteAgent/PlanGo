import { Building2, Flame, MapPin, RefreshCw, Sparkles } from "lucide-react";
import { Clock, Tags, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppleButton, SoftTag } from "../../components/ui";
import { usePlanStream } from "../../hooks/usePlanStream";
import type { ClientGeoLocation, Plan } from "../../types/agent";
import { AUTO_SUBMIT_EVENT, type AutoSubmitPayload } from "../../utils/autoSubmitEvent";
import type { StoredChatMessage } from "../../utils/conversationStore";
import { createId } from "../../utils/id";
import { ChatPanelV2 } from "./ChatPanelV2";
import { WelcomeHero } from "./WelcomeHero";

interface HomeInspirationPoi {
  id: string;
  name: string;
  category?: string;
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

function isInBeijing(lat: number, lng: number) {
  return lng >= 115.4 && lng <= 117.6 && lat >= 39.4 && lat <= 41.1;
}

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
  const [geoLocation, setGeoLocation] = useState<ClientGeoLocation | null>(null);
  const [selectedInspiration, setSelectedInspiration] = useState<HomeInspirationPoi | null>(null);
  const isCurrentConversationRunning = isRunning && streamConversationId === conversationId;

  useEffect(() => {
    if (!("geolocation" in navigator)) return;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        if (!isInBeijing(latitude, longitude)) {
          setGeoLocation(null);
          return;
        }
        setGeoLocation({
          lat: latitude,
          lng: longitude,
          accuracy_meters: Number.isFinite(accuracy) ? accuracy : null,
          source: "browser",
          updated_at: new Date(position.timestamp || Date.now()).toISOString()
        });
      },
      () => setGeoLocation(null),
      { enableHighAccuracy: false, maximumAge: 5 * 60 * 1000, timeout: 8000 }
    );
  }, []);

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
            id: createId(),
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
          id: createId(),
          role: "user",
          content: trimmedGoal
        }
      ];

      onMessagesChange(nextMessages);
      streamBaseMessagesRef.current = nextMessages;
      streamRunIdRef.current = createId();
      processedRunIdRef.current = "";
      setStreamConversationId(conversationId);

      void run({
        goal: trimmedGoal,
        city: "beijing",
        execute: false,
        fail_next_restaurant_booking: false,
        session_id: conversationId,
        geo_location: geoLocation,
        history: messages.map((message) => ({
          role: message.role === "assistant" ? "assistant" : "user",
          content: message.content
        }))
      });
    },
    [conversationId, geoLocation, isRunning, messages, onMessagesChange, run]
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
                    onClick={() => setSelectedInspiration(poi)}
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
      <InspirationDetailDrawer
        poi={selectedInspiration}
        onClose={() => setSelectedInspiration(null)}
        onWantToGo={(poi) => {
          setSelectedInspiration(null);
          submit(`我想去 ${poi.name}，帮我搭配一个本地生活方案。`);
        }}
      />
    </div>
  );
}

function InspirationDetailDrawer({
  poi,
  onClose,
  onWantToGo
}: {
  poi: HomeInspirationPoi | null;
  onClose: () => void;
  onWantToGo: (poi: HomeInspirationPoi) => void;
}) {
  if (!poi) return null;

  const tags = poi.tags.length ? poi.tags : [poi.tag || "本地生活"];

  return (
    <aside className="drawer" aria-label="灵感详情" onMouseDown={onClose}>
      <div className="drawer-panel inspiration-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>灵感推荐</span>
            <h2>{poi.name}</h2>
          </div>
          <AppleButton type="button" variant="ghost" size="sm" onClick={onClose} aria-label="关闭灵感详情">
            <X size={18} />
          </AppleButton>
        </header>
        <div className="place-cover">
          {poi.image_url ? <img src={poi.image_url} alt={poi.name} /> : <span>{poi.name.slice(0, 1)}</span>}
        </div>
        <div className="drawer-content">
          <section className="drawer-section">
            <strong>推荐信息</strong>
            <p>{poi.tag || "适合作为本次本地生活规划的候选地点。点击底部按钮后，我会围绕这里搭配完整方案。"}</p>
          </section>
          <div className="place-facts">
            <span>
              <MapPin size={16} />
              {poi.category || "本地生活"}
            </span>
            <span>
              <Clock size={16} />
              {poi.duration_text || "1-3h"}
            </span>
            <span>
              <Tags size={16} />
              {poi.tag || tags[0] || "推荐"}
            </span>
          </div>
          <div className="tag-row">
            {tags.slice(0, 6).map((tag) => (
              <SoftTag key={tag}>{tag}</SoftTag>
            ))}
          </div>
        </div>
        <div className="drawer-footer">
          <AppleButton type="button" onClick={() => onWantToGo(poi)}>
            想去此地
          </AppleButton>
        </div>
      </div>
    </aside>
  );
}
