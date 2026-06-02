import { ArrowUp, StopCircle } from "lucide-react";
import { useState } from "react";

interface ChatInputProps {
  disabled?: boolean;
  running?: boolean;
  placeholder?: string;
  onSubmit: (value: string) => void;
  onCancel?: () => void;
}

export function ChatInput({ disabled = false, running = false, placeholder, onSubmit, onCancel }: ChatInputProps) {
  const [value, setValue] = useState("");
  const canSubmit = Boolean(value.trim()) && !disabled && !running;

  const submit = () => {
    const next = value.trim();
    if (!next || running || disabled) return;
    setValue("");
    onSubmit(next);
  };

  return (
    <div className="chat-input-shell">
      <label className="sr-only" htmlFor="plango-chat-input">
        输入本地生活规划需求
      </label>
      <textarea
        id="plango-chat-input"
        value={value}
        disabled={disabled}
        rows={1}
        placeholder={placeholder ?? "想去哪儿？和谁一起？预算和时间大概多少？"}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      {running ? (
        <button type="button" className="chat-input-action is-cancel" onClick={onCancel} aria-label="停止生成">
          <StopCircle size={18} />
        </button>
      ) : (
        <button type="button" className="chat-input-action" disabled={!canSubmit} onClick={submit} aria-label="发送需求">
          <ArrowUp size={18} />
        </button>
      )}
    </div>
  );
}
