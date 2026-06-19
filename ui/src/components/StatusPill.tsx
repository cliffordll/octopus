import type { HTMLAttributes, PropsWithChildren } from "react";

export function StatusPill({
  children,
  className = "",
  status,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLSpanElement> & { status?: string | null }>) {
  const statusClass = status ? status.replace(/[^a-zA-Z0-9_-]/g, "_") : "";
  return (
    <span className={`agent-run-status-pill ${statusClass} ${className}`.trim()} {...props}>
      {children}
    </span>
  );
}
