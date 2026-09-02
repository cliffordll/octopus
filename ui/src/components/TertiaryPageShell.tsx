import type { HTMLAttributes, PropsWithChildren } from "react";

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
  children,
  className,
  ...props
}: PropsWithChildren<HTMLAttributes<HTMLElement>>) {
  return (
    <header className={classNames("page-header tertiary-page-header", className)} {...props}>
      {children}
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
