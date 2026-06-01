import { useEffect, useState } from "react";
import { usePlanStream } from "../../hooks/usePlanStream";
import type { Plan } from "../../types/agent";
import { ChatPanel, type ChatMessage } from "./ChatPanel";
import { RequirementCards } from "./RequirementCards";
import { WelcomeHero } from "./WelcomeHero";

interface ChatHomeProps {
  onPlanReady: (plan: Plan) => void;
}

export function ChatHome({ onPlanReady }: ChatHomeProps) {
  const { isRunning, events, plan, assistantText, run, cancel } = usePlanStream();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "你好，我是 PlanGo。告诉我出行人数、时间、预算和偏好，我会帮你生成路线、行程和可执行操作。"
    }
  ]);
  const [lastAssistantText, setLastAssistantText] = useState("");

  useEffect(() => {
    if (!isRunning && assistantText && assistantText !== lastAssistantText) {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: assistantText
        }
      ]);
      setLastAssistantText(assistantText);
    }
  }, [assistantText, isRunning, lastAssistantText]);

  useEffect(() => {
    if (!isRunning && plan) {
      const timer = window.setTimeout(() => onPlanReady(plan), 360);
      return () => window.clearTimeout(timer);
    }
  }, [isRunning, onPlanReady, plan]);

  const submit = (goal: string) => {
    const nextMessages: ChatMessage[] = [
      ...messages,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: goal
      }
    ];
    setMessages(nextMessages);
    void run({
      goal,
      city: "beijing",
      execute: false,
      fail_next_restaurant_booking: false,
      history: messages.map((message) => ({ role: message.role === "assistant" ? "assistant" : "user", content: message.content }))
    });
  };

  return (
    <div className="chat-home">
      <div className="chat-home-inner">
        <WelcomeHero />
        <ChatPanel
          messages={messages}
          assistantDraft={isRunning ? assistantText : ""}
          events={events}
          isRunning={isRunning}
          onSubmit={submit}
          onCancel={cancel}
        />
        <RequirementCards onPick={submit} />
      </div>
    </div>
  );
}
