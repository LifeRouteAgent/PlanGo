import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";
import { AppleButton } from "./AppleButton";

interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

export function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return (
    <section className="state-page">
      <div className="state-icon">{icon ?? <Sparkles size={26} />}</div>
      <h1>{title}</h1>
      <p>{description}</p>
      {actionLabel && onAction && (
        <AppleButton type="button" onClick={onAction}>
          {actionLabel}
        </AppleButton>
      )}
    </section>
  );
}
