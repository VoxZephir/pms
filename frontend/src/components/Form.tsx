/** Form fields: a label above, the error under it when refused, the typed
 * value kept -- a refused field says what it wanted instead of emptying. */
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

import { cx } from "./ui";

export function Field({
  label, error, hint, children, className,
}: { label: ReactNode; error?: string; hint?: ReactNode; children: (id: string, describedBy?: string) => ReactNode; className?: string }) {
  const id = useId();
  const errId = `${id}-err`;
  const hintId = `${id}-hint`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[12.5px] font-medium text-ink-2">{label}</label>
      {children(id, error ? errId : hint ? hintId : undefined)}
      {error ? <p id={errId} role="alert" className="text-[12.5px] text-critical">{error}</p>
        : hint ? <p id={hintId} className="text-[12px] text-muted">{hint}</p> : null}
    </div>
  );
}

const base = "h-11 w-full min-w-0 rounded-xl border bg-surface px-3 text-[16px] text-ink outline-none transition focus:border-accent sm:h-10 sm:text-[14px]";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ invalid, className, ...rest }, ref) {
    return <input ref={ref} aria-invalid={invalid || undefined}
                  className={cx(base, invalid ? "border-critical" : "border-hairline-2", className)} {...rest} />;
  },
);

export function Select({ invalid, className, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return <select aria-invalid={invalid || undefined}
                 className={cx(base, "pr-8", invalid ? "border-critical" : "border-hairline-2", className)} {...rest} />;
}
