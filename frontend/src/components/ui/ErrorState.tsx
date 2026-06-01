import { AlertCircle } from "lucide-react";
import { AppleButton } from "./AppleButton";

interface ErrorStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function ErrorState({ title, description, actionLabel, onAction }: ErrorStateProps) {
  return (
    <section className="state-page is-error">
      <div className="state-icon">
        <AlertCircle size={26} />
      </div>
      <h1>{title}</h1>
      <p>{description}</p>
      {actionLabel && onAction && (
        <AppleButton type="button" variant="secondary" onClick={onAction}>
          {actionLabel}
        </AppleButton>
      )}
    </section>
  );
}
