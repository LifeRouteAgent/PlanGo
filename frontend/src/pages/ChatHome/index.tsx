import { useEffect, useState } from "react";
import { usePlanStream } from "../../hooks/usePlanStream";
import type { Plan } from "../../types/agent";
import type { ConversationRecord, StoredChatMessage } from "../../utils/conversationStore";
import { ChatPanelV2 } from "./ChatPanelV2";
import { RequirementCards } from "./RequirementCards";
import { ChatSidebar } from "./ChatSidebar";
import { WelcomeHero } from "./WelcomeHero";

interface ChatHomeProps {
  conversationId: string;
  messages: StoredChatMessage[];
  conversations: ConversationRecord[];
  hasPlan: boolean;
  onMessagesChange: (messages: StoredChatMessage[]) => void;
  onPlanReady: (plan: Plan) => void;
  onOpenPlans: () => void;
  onOpenDetail: () => void;
  onNewConversation: () => void;
  onLoadConversation: (conversationId: string) => void;
}

export function ChatHome({
  conversationId,
  messages,
  conversations,
  hasPlan,
  onMessagesChange,
  onPlanReady,
  onOpenPlans,
  onOpenDetail,
  onNewConversation,
  onLoadConversation
}: ChatHomeProps) {
  const { isRunning, events, plan, assistantText, run, cancel } = usePlanStream();
  const [lastAssistantText, setLastAssistantText] = useState("");

  useEffect(() => {
    if (!isRunning && assistantText && assistantText !== lastAssistantText) {
      onMessagesChange([
        ...messages,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: assistantText
        }
      ]);
      setLastAssistantText(assistantText);
    }
  }, [assistantText, isRunning, lastAssistantText, messages, onMessagesChange]);

  useEffect(() => {
    if (!isRunning && plan) {
      const timer = window.setTimeout(() => onPlanReady(plan), 360);
      return () => window.clearTimeout(timer);
    }
  }, [isRunning, onPlanReady, plan]);

  const submit = (goal: string) => {
    const nextMessages: StoredChatMessage[] = [
      ...messages,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: goal
      }
    ];
    onMessagesChange(nextMessages);
    void run({
      goal,
      city: "beijing",
      execute: false,
      fail_next_restaurant_booking: false,
      session_id: conversationId,
      history: nextMessages.map((message) => ({
        role: message.role === "assistant" ? "assistant" : "user",
        content: message.content
      }))
    });
  };

  return (
    <div className="chat-home">
      <ChatSidebar
        conversationId={conversationId}
        conversations={conversations}
        onNewConversation={onNewConversation}
        onLoadConversation={onLoadConversation}
      />

      <div className="chat-home-main">
        <div className="chat-home-inner">
          <WelcomeHero />
          <div className="chat-workbench">
            <ChatPanelV2
              messages={messages}
              assistantDraft={isRunning ? assistantText : ""}
              events={events}
              isRunning={isRunning}
              hasPlan={hasPlan}
              onSubmit={submit}
              onCancel={cancel}
              onOpenPlans={onOpenPlans}
              onOpenDetail={onOpenDetail}
            />
            <aside className="home-inspiration-panel" aria-label="灵感推荐">
              <section>
                <strong>快速开始</strong>
                <div className="inspiration-actions">
                  {["附近推荐", "热门聚会", "今日特色", "收藏地点"].map((item) => (
                    <button type="button" key={item} onClick={() => submit(item)}>
                      {item}
                    </button>
                  ))}
                </div>
              </section>
              <section>
                <strong>灵感推荐</strong>
                <button type="button" className="inspiration-route" onClick={() => submit("周末想安排一个轻松的 Citywalk 半日游，预算适中，路线别太绕。")}>
                  <span>Citywalk 半日游</span>
                  <small>经典路线 · 适合拍照 · 3 个地点</small>
                </button>
                <button type="button" className="inspiration-route" onClick={() => submit("想找亲子室内乐园，再配一个适合孩子的餐厅。")}>
                  <span>亲子室内乐园</span>
                  <small>轻松有趣 · 孩子喜欢 · 2-3 个地点</small>
                </button>
                <button type="button" className="inspiration-route" onClick={() => submit("和朋友出去吃饭唱歌，预算适中，别太远。")}>
                  <span>美食聚会之旅</span>
                  <small>吃饭唱歌 · 朋友局 · 2 个地点</small>
                </button>
              </section>
            </aside>
          </div>
          <RequirementCards onPick={submit} />
        </div>
      </div>
    </div>
  );
}
