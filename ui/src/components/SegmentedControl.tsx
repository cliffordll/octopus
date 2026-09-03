import type { ReactNode } from "react";

export interface SegmentedControlOption<T extends string> {
  disabled?: boolean;
  label: ReactNode;
  value: T;
}

export function SegmentedControl<T extends string>({
  ariaLabel,
  className = "",
  disabled = false,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  onChange: (value: T) => void;
  options: readonly SegmentedControlOption<T>[];
  value: T;
}) {
  return (
    <div aria-label={ariaLabel} className={`segmented-control ${className}`.trim()} role="group">
      {options.map((option) => (
        <button
          aria-pressed={value === option.value}
          className={value === option.value ? "active" : ""}
          disabled={disabled || option.disabled}
          key={option.value}
          onClick={() => value !== option.value && onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
