import type { ReactNode } from "react";

export function FilePreview({
  actions,
  children,
  className = "",
  status,
  testId,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  status?: ReactNode;
  testId?: string;
  title: ReactNode;
}) {
  return (
    <section className={`file-preview${className ? ` ${className}` : ""}`} data-testid={testId}>
      <div className="file-preview-toolbar">
        <div>
          <h3>{title}</h3>
          {status && <p>{status}</p>}
        </div>
        {actions && <div className="file-preview-actions">{actions}</div>}
      </div>
      <div className="file-preview-content">{children}</div>
    </section>
  );
}
