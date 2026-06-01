import type { ButtonHTMLAttributes, ReactNode } from "react";

interface SoftTagProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  selected?: boolean;
  tone?: "blue" | "mint" | "neutral" | "warning";
}

export function SoftTag({ children, selected = false, tone = "neutral", className = "", ...props }: SoftTagProps) {
  const classes = ["soft-tag", `soft-tag-${tone}`, selected ? "is-selected" : "", className].filter(Boolean).join(" ");

  return (
    <button type="button" className={classes} {...props}>
      {children}
    </button>
  );
}
