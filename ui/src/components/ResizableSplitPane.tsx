import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

export function ResizableSplitPane({
  children,
  className = "",
  defaultWidth = 720,
  maxWidth = 900,
  minWidth = 420,
  storageKey,
}: {
  children: [ReactNode, ReactNode];
  className?: string;
  defaultWidth?: number;
  maxWidth?: number;
  minWidth?: number;
  storageKey?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [leftWidth, setLeftWidth] = useState(defaultWidth);

  useEffect(() => {
    const savedWidth = storageKey ? Number(window.localStorage.getItem(storageKey)) : Number.NaN;
    setLeftWidth(Number.isFinite(savedWidth) && savedWidth > 0
      ? Math.min(maxWidth, Math.max(minWidth, savedWidth))
      : defaultWidth);
  }, [defaultWidth, maxWidth, minWidth, storageKey]);

  function updateWidth(nextWidth: number) {
    const availableWidth = containerRef.current?.getBoundingClientRect().width ?? maxWidth;
    const upperBound = Math.min(maxWidth, Math.max(minWidth, availableWidth - 320));
    const width = Math.round(Math.min(upperBound, Math.max(minWidth, nextWidth)));
    setLeftWidth(width);
    if (storageKey) window.localStorage.setItem(storageKey, String(width));
  }

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = leftWidth;
    event.currentTarget.setPointerCapture(event.pointerId);
    const handlePointerMove = (moveEvent: globalThis.PointerEvent) => updateWidth(startWidth + moveEvent.clientX - startX);
    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    updateWidth(leftWidth + (event.key === "ArrowRight" ? 20 : -20));
  }

  return (
    <div
      className={`resizable-split-pane${className ? ` ${className}` : ""}`}
      ref={containerRef}
      style={{ "--split-pane-left-width": `${leftWidth}px` } as CSSProperties}
    >
      <div className="resizable-split-pane-left">{children[0]}</div>
      <button
        aria-label="调整信息栏宽度"
        aria-orientation="vertical"
        aria-valuemax={maxWidth}
        aria-valuemin={minWidth}
        aria-valuenow={leftWidth}
        className="resizable-split-pane-divider"
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        role="separator"
        type="button"
      />
      <div className="resizable-split-pane-right">{children[1]}</div>
    </div>
  );
}
