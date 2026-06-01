import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

interface AppleButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  full?: boolean;
}

export function AppleButton({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  full = false,
  disabled,
  className = "",
  ...props
}: AppleButtonProps) {
  const classes = [
    "apple-button",
    `apple-button-${variant}`,
    `apple-button-${size}`,
    full ? "is-full" : "",
    loading ? "is-loading" : "",
    className
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button className={classes} disabled={disabled || loading} {...props}>
      {loading && <Loader2 size={16} className="apple-button-spinner" />}
      {children}
    </button>
  );
}
