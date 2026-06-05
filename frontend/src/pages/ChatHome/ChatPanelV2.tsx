import { ArrowRight, MapPinned } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AppleButton, ChatBubble, ChatInput, GlassCard, LoadingSteps, MarkdownMessage } from "../../components/ui";
import type { TimelineEvent } from "../../hooks/usePlanStream";
import { isPlanLinkMessage, type StoredChatMessage } from "../../utils/conversationStore";
import { QuickChips } from "./QuickChips";

const defaultPrompts = [
  "今天下午想和朋友去喝咖啡、逛逛展览，预算人均200左右",
  "周末带爸妈找个舒服的地方吃饭，不要太远，开车1小时以内",
  "和女朋友约会，想找浪漫的地方，晚上吃饭看夜景"
];

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
  const [selectedPreferences, setSelectedPreferences] = useState<string[]>([]);
  const [chipVariant, setChipVariant] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, assistantDraft, events, hasPlan]);

  const toggleChip = (chip: string) => {
    setSelectedPreferences((current) =>
      current.includes(chip) ? current.filter((item) => item !== chip) : [...current, chip]
    );
  };

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || isRunning) return;
    const merged = selectedPreferences.length ? `${trimmed}，偏好：${selectedPreferences.join("，")}` : trimmed;
    setSelectedPreferences([]);
    onSubmit(merged);
  };

  const showDefaultPrompts = messages.length <= 1 && !isRunning && !hasPlan;

  return (
    <GlassCard className="chat-card chat-card-hero" as="section">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((message) =>
          isPlanLinkMessage(message) ? (
            <PlanLinkCard key={message.id} onOpenPlans={onOpenPlans} onOpenDetail={onOpenDetail} />
          ) : (
            <ChatBubble key={message.id} role={message.role}>
              {message.role === "assistant" ? <MarkdownMessage content={message.content} /> : <p>{message.content}</p>}
            </ChatBubble>
          )
        )}

        {assistantDraft ? (
          <ChatBubble role="assistant">
            <MarkdownMessage content={assistantDraft} />
          </ChatBubble>
        ) : null}

        {events.length ? <LoadingSteps events={events} isRunning={isRunning} /> : null}
      </div>

      {showDefaultPrompts ? (
        <div className="chat-default-prompts" aria-label="快速需求示例">
          {defaultPrompts.map((prompt) => (
            <button type="button" key={prompt} onClick={() => submit(prompt)}>
              <span>{prompt}</span>
              <ArrowRight size={15} />
            </button>
          ))}
        </div>
      ) : null}

      <ChatInput running={isRunning} onCancel={onCancel} onSubmit={submit} />
      <QuickChips
        selected={selectedPreferences}
        variant={chipVariant}
        onToggle={toggleChip}
        onRefresh={() => setChipVariant((value) => value + 1)}
      />
    </GlassCard>
  );
}

function PlanLinkCard({ onOpenPlans, onOpenDetail }: { onOpenPlans: () => void; onOpenDetail: () => void }) {
  return (
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
  );
}
