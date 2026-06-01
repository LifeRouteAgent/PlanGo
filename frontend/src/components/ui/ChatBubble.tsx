import type { ReactNode } from "react";

interface ChatBubbleProps {
  role: "assistant" | "user";
  children: ReactNode;
}

export function ChatBubble({ role, children }: ChatBubbleProps) {
  return (
    <article className={`chat-bubble is-${role}`}>
      <div>{children}</div>
    </article>
  );
}
