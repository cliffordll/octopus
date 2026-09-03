import { Children, Fragment, isValidElement, type HTMLAttributes, type PropsWithChildren, type ReactNode } from "react";

function classNames(base: string, className?: string) {
  return className ? `${base} ${className}` : base;
}

export function TertiaryPageShell({
  children,
  className,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div className={classNames("tertiary-page-shell", className)} {...props}>
      {children}
    </div>
  );
}

export function TertiaryPageHeader({
  actions,
  eyebrow,
  supporting,
  title,
  variant = "default",
  ...props
}: Omit<HTMLAttributes<HTMLElement>, "children" | "className" | "title"> & {
  actions?: ReactNode;
  eyebrow: ReactNode;
  supporting?: ReactNode;
  title: ReactNode;
  variant?: "canvas" | "contained" | "default";
}) {
  const variantClassName = variant === "default" ? undefined : `tertiary-page-header-${variant}`;
  return (
    <header className={classNames("page-header tertiary-page-header", variantClassName)} {...props}>
      <div className="tertiary-page-heading">
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <div className="tertiary-page-supporting">{supporting}</div>
      </div>
      {actions !== undefined && (
        <div className="tertiary-page-actions">{actions}</div>
      )}
    </header>
  );
}

export function TertiaryPageViewport({
  children,
  className,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div className={classNames("tertiary-page-viewport", className)} {...props}>
      {children}
    </div>
  );
}

/**
 * Applies the shared tertiary-page frame to full-width workspace content.
 * Pages provide semantic header slots while the fixed header and scrolling
 * body remain a single global layout contract.
 */
export function TertiaryPageFrame({
  children,
  contained = false,
}: PropsWithChildren<{ contained?: boolean }>) {
  const items = Children.toArray(children);
  const alreadyFramed = items.some((item) => isValidElement(item) && item.type === TertiaryPageShell);
  if (alreadyFramed) return <Fragment>{children}</Fragment>;

  const headerIndex = items.findIndex((item) => isValidElement(item) && item.type === TertiaryPageHeader);
  if (headerIndex < 0) {
    return (
      <TertiaryPageShell className="tertiary-page-shell-titleless">
        <TertiaryPageViewport className={contained ? "tertiary-page-viewport-contained" : undefined}>
          {items}
        </TertiaryPageViewport>
      </TertiaryPageShell>
    );
  }

  const header = items[headerIndex] as ReactNode;
  const body = items.filter((_, index) => index !== headerIndex);
  return (
    <TertiaryPageShell className="tertiary-page-shell-titled">
      {header}
      <TertiaryPageViewport className={contained ? "tertiary-page-viewport-contained" : undefined}>
        {body}
      </TertiaryPageViewport>
    </TertiaryPageShell>
  );
}
