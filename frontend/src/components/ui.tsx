/** The handful of primitives every page is built from. */
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import {
  forwardRef, useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type ComponentProps, type ReactNode,
} from "react";
import { Link, type LinkProps } from "react-router";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ card */

export function Card({
  className, children, ...rest
}: ComponentProps<"section">) {
  return (
    <section
      className={cx(
        // min-w-0: a card in a grid track must shrink to it, or a wide
        // child (a segmented control, a table) widens the page.
        "min-w-0 rounded-card border border-hairline bg-surface shadow-card",
        className,
      )}
      {...rest}
    >
      {children}
    </section>
  );
}

/** A panel: title, a hint in the margin, controls on the right, content. */
export function Panel({
  id, title, hint, actions, children, className, foldable, defaultOpen = true, bleed,
}: {
  id?: string;
  title: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  foldable?: boolean;
  defaultOpen?: boolean;
  /** Content runs to the card's edges (charts that scroll). */
  bleed?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  // Every panel is a section of the page's contents (shell/Sections.tsx),
  // which needs an id to jump to and unfolds a folded panel on arrival.
  const sectionId = id ?? `s${bodyId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !foldable) return;
    const unfold = () => setOpen(true);
    el.addEventListener("section:open", unfold);
    return () => el.removeEventListener("section:open", unfold);
  }, [foldable]);
  const head = (
    <div className="min-w-[min(100%,220px)] flex-1">
      <h2 className="text-[17px] font-semibold leading-snug tracking-[-0.015em] text-ink">{title}</h2>
      {hint && <p className="mt-0.5 text-[12.5px] leading-snug text-muted">{hint}</p>}
    </div>
  );
  return (
    <Card id={sectionId} ref={ref} data-section="" className={cx("scroll-mt-24", className)}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2.5 px-4 pt-4 sm:px-5 sm:pt-5">
        {foldable ? (
          <button
            type="button"
            className="-m-1 flex min-w-0 flex-1 items-center gap-2 rounded-lg p-1 text-left"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((v) => !v)}
          >
            <ChevronDown
              size={16}
              className={cx("shrink-0 text-muted transition-transform", !open && "-rotate-90")}
            />
            {head}
          </button>
        ) : head}
        {actions && (!foldable || open) && (
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>
        )}
      </header>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={bodyId}
            key="body"
            initial={foldable ? { height: 0, opacity: 0 } : false}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className={cx("pb-4 pt-3 sm:pb-5", bleed ? "" : "px-4 sm:px-5")}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
      {foldable && !open && <div className="h-4 sm:h-5" />}
    </Card>
  );
}

/* --------------------------------------------------------------- buttons */

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-ink text-page hover:opacity-90 shadow-sm",
  secondary:
    "bg-surface text-ink border border-hairline-2 hover:bg-surface-2 shadow-[var(--shadow-sm)]",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "bg-critical text-white hover:opacity-90",
};

const SIZES = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-10 px-4 text-[14px] gap-2 rounded-xl",
  lg: "h-12 px-5 text-[15px] gap-2 rounded-xl",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZES }
>(function Button({ variant = "secondary", size = "md", className, ...rest }, ref) {
  return (
    <button
      ref={ref}
      className={cx(
        "inline-flex select-none items-center justify-center whitespace-nowrap font-medium transition",
        "disabled:pointer-events-none disabled:opacity-45 active:scale-[0.98]",
        VARIANTS[variant], SIZES[size], className,
      )}
      {...rest}
    />
  );
});

export function ButtonLink({
  variant = "secondary", size = "md", className, ...rest
}: LinkProps & { variant?: Variant; size?: keyof typeof SIZES }) {
  return (
    <Link
      className={cx(
        "inline-flex select-none items-center justify-center whitespace-nowrap font-medium no-underline transition active:scale-[0.98]",
        VARIANTS[variant], SIZES[size], className,
      )}
      {...rest}
    />
  );
}

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }
>(function IconButton({ label, className, children, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "grid size-9 shrink-0 place-items-center rounded-xl text-ink-2 transition",
        "hover:bg-surface-2 hover:text-ink active:scale-95",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

/* ------------------------------------------------------------- segmented */

/** A segmented control whose pill slides to the active option. Options
 * are links when `href` is given (the view lives in the URL), buttons
 * otherwise. */
export function Segmented<T extends string | number>({
  options, value, onChange, hrefFor, label, size = "md", className, columns,
}: {
  options: { id: T; label: ReactNode; title?: string }[];
  value: T;
  onChange?: (id: T) => void;
  hrefFor?: (id: T) => string;
  label: string;
  size?: "sm" | "md";
  className?: string;
  /** Lay the options on a grid of this many columns rather than one row that
   * scrolls: for a set too long for its box (seven grains in a popover). */
  columns?: number;
}) {
  const group = useId();
  return (
    <div
      role="group"
      aria-label={label}
      className={cx(
        "relative rounded-xl bg-surface-2 p-[3px]",
        columns ? "grid w-full gap-y-[3px]" : "inline-flex max-w-full overflow-x-auto no-scrollbar",
        className,
      )}
      style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}
    >
      {options.map((o) => {
        const active = o.id === value;
        const inner = (
          <>
            {active && (
              <motion.span
                layoutId={`seg-${group}`}
                className="absolute inset-0 rounded-[9px] bg-surface shadow-[0_1px_2px_rgba(0,0,0,.08),0_0_0_1px_var(--hairline)]"
                transition={{ type: "spring", stiffness: 500, damping: 38 }}
              />
            )}
            <span className="relative">{o.label}</span>
          </>
        );
        const cls = cx(
          "relative shrink-0 whitespace-nowrap rounded-[9px] font-medium transition-colors no-underline",
          !!columns && "text-center",
          size === "sm" ? "px-2.5 py-1 text-[12.5px]" : "px-3 py-1.5 text-[13.5px]",
          active ? "text-ink" : "text-ink-2 hover:text-ink",
        );
        return hrefFor ? (
          <Link
            key={String(o.id)}
            to={hrefFor(o.id)}
            preventScrollReset
            className={cls}
            title={o.title}
            aria-current={active ? "true" : undefined}
            onClick={() => onChange?.(o.id)}
          >
            {inner}
          </Link>
        ) : (
          <button
            key={String(o.id)}
            type="button"
            className={cls}
            title={o.title}
            aria-pressed={active}
            onClick={() => onChange?.(o.id)}
          >
            {inner}
          </button>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- bits */

export function Chip({
  children, tone = "neutral", className, title,
}: { children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" | "accent"; className?: string; title?: string }) {
  const tones = {
    neutral: "bg-surface-2 text-ink-2",
    good: "bg-[color-mix(in_srgb,var(--good)_12%,transparent)] text-good",
    bad: "bg-[color-mix(in_srgb,var(--critical)_12%,transparent)] text-critical",
    warn: "bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] text-warn",
    accent: "bg-[color-mix(in_srgb,var(--s0)_12%,transparent)] text-accent",
  };
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium",
        tones[tone], className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ color, hollow, className }: { color: string; hollow?: boolean; className?: string }) {
  return (
    <i
      aria-hidden
      className={cx("inline-block size-2.5 shrink-0 rounded-full", className)}
      style={hollow ? { boxShadow: `inset 0 0 0 1.5px ${color}` } : { background: color }}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function Callout({
  tone = "info", title, children, icon, action, className,
}: {
  tone?: "info" | "warn" | "good" | "bad";
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-[color-mix(in_srgb,var(--s0)_25%,transparent)] bg-[color-mix(in_srgb,var(--s0)_7%,var(--surface))]",
    warn: "border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,var(--surface))]",
    good: "border-[color-mix(in_srgb,var(--good)_25%,transparent)] bg-[color-mix(in_srgb,var(--good)_7%,var(--surface))]",
    bad: "border-[color-mix(in_srgb,var(--critical)_25%,transparent)] bg-[color-mix(in_srgb,var(--critical)_7%,var(--surface))]",
  };
  return (
    <div role="status" className={cx("flex gap-3 rounded-2xl border px-4 py-3 text-[14px]", tones[tone], className)}>
      {icon && <div className="mt-0.5 shrink-0">{icon}</div>}
      <div className="min-w-0 flex-1 text-ink-2">
        {title && <div className="font-semibold text-ink">{title}</div>}
        {children}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("mt-3 text-[12.5px] leading-relaxed text-muted", className)}>{children}</p>;
}

/** A disclosure for secondary detail: a table behind a chart, a long list. */
export function Reveal({
  summary, children, className, defaultOpen = false,
}: { summary: ReactNode; children: ReactNode; className?: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg py-1 text-[13px] font-medium text-ink-2 hover:text-ink"
      >
        <ChevronDown size={14} className={cx("transition-transform", !open && "-rotate-90")} />
        {summary}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** A bar in a horizontal bar list: the track and its fill. */
export function Track({ value, color, className }: { value: number; color: string; className?: string }) {
  return (
    <span className={cx("relative block h-2 overflow-hidden rounded-full bg-surface-2", className)}>
      <motion.i
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ background: color }}
        initial={false}
        animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        transition={{ type: "spring", stiffness: 260, damping: 32 }}
      />
    </span>
  );
}

export function Slot(slot: number): string {
  return `var(--s${slot})`;
}
