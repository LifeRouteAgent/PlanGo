import type { HTMLAttributes, ReactNode } from "react";

interface GlassCardProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  as?: "article" | "section" | "div" | "aside";
  selected?: boolean;
  hoverable?: boolean;
}

export function GlassCard({
  children,
  as: Component = "div",
  selected = false,
  hoverable = false,
  className = "",
  ...props
}: GlassCardProps) {
  const classes = [
    "glass-card",
    hoverable ? "is-hoverable" : "",
    selected ? "is-selected" : "",
    className
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Component className={classes} {...props}>
      {children}
    </Component>
  );
}
