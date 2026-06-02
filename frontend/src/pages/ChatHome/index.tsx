import { useEffect, useState } from "react";
import { usePlanStream } from "../../hooks/usePlanStream";
import type { Plan } from "../../types/agent";
import type { ConversationRecord, StoredChatMessage } from "../../utils/conversationStore";
import { ChatPanel } from "./ChatPanel";
import { RequirementCards } from "./RequirementCards";
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
      <div className="chat-home-inner">
        <WelcomeHero />
        <ChatPanel
          conversationId={conversationId}
          conversations={conversations}
          messages={messages}
          assistantDraft={isRunning ? assistantText : ""}
          events={events}
          isRunning={isRunning}
          hasPlan={hasPlan}
          onSubmit={submit}
          onCancel={cancel}
          onOpenPlans={onOpenPlans}
          onOpenDetail={onOpenDetail}
          onNewConversation={onNewConversation}
          onLoadConversation={onLoadConversation}
        />
        <RequirementCards onPick={submit} />
      </div>
    </div>
  );
}
