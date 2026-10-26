/** The chart tooltip: a card that follows the pointer inside the chart and
 * stays on screen. Rows are name / value / swatch.
 *
 * The card is drawn in a portal, fixed to the viewport, and clamped to it
 * once measured: panels clip their content (rounded corners, scroll boxes),
 * so a card positioned inside the chart was cut off at the panel's bottom
 * edge as soon as it had more rows than the chart was tall. An invisible
 * anchor at (x, y) in the chart says where the pointer is on screen. */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface TipRow {
  name: ReactNode;
  value: ReactNode;
  color?: string;
  dashed?: boolean;
  strong?: boolean;
}

const GAP = 14;
const MARGIN = 8;

export function ChartTip({
  x, y, width, title, rows, footer, hint,
}: {
  x: number;
  y: number;
  /** The chart's width: the card goes left of the pointer past the middle. */
  width: number;
  title: ReactNode;
  rows: TipRow[];
  footer?: ReactNode;
  hint?: ReactNode;
}) {
  const anchor = useRef<HTMLSpanElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [tick, setTick] = useState(0);
  const flip = x > width / 2;

  // Scrolling moves the chart under a card fixed to the viewport: follow it.
  useLayoutEffect(() => {
    const again = () => setTick((n) => n + 1);
    window.addEventListener("scroll", again, { capture: true, passive: true });
    window.addEventListener("resize", again);
    return () => {
      window.removeEventListener("scroll", again, { capture: true });
      window.removeEventListener("resize", again);
    };
  }, []);

  useLayoutEffect(() => {
    const a = anchor.current, c = card.current;
    if (!a || !c) return;
    const at = a.getBoundingClientRect();
    const w = c.offsetWidth, h = c.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    let left = flip ? at.left - GAP - w : at.left + GAP;
    // No room on the preferred side: try the other before clamping over the pointer.
    if (flip && left < MARGIN) left = at.left + GAP;
    else if (!flip && left + w > vw - MARGIN) left = at.left - GAP - w;
    left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, vw - w - MARGIN));
    const top = Math.min(Math.max(at.top, MARGIN), Math.max(MARGIN, vh - h - MARGIN));
    setPos((p) => (p && p.left === left && p.top === top ? p : { left, top }));
  }, [x, y, flip, rows, footer, hint, title, tick]);

  return (
    <>
      <span ref={anchor} aria-hidden className="pointer-events-none absolute size-0" style={{ left: x, top: Math.max(0, y) }} />
      {createPortal(
        <div
          ref={card}
          role="presentation"
          data-chart-tip
          className="pointer-events-none fixed z-50 w-max min-w-[170px] max-w-[260px] rounded-2xl border border-hairline bg-surface/95 px-3 py-2.5 text-[12.5px] shadow-pop backdrop-blur-md transition-opacity duration-100"
          style={{ left: pos?.left ?? 0, top: pos?.top ?? 0, opacity: pos ? 1 : 0 }}
        >
          <div className="mb-1.5 font-semibold text-ink">{title}</div>
          <div className="space-y-1">
            {rows.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                {r.color && (
                  r.dashed
                    ? <i className="h-0 w-3 shrink-0 border-t-2 border-dashed" style={{ borderColor: r.color }} />
                    : <i className="size-2.5 shrink-0 rounded-[3px]" style={{ background: r.color }} />
                )}
                <span className="min-w-0 flex-1 truncate text-ink-2">{r.name}</span>
                <span className={`num whitespace-nowrap ${r.strong ? "font-semibold text-ink" : "text-ink"}`}>{r.value}</span>
              </div>
            ))}
          </div>
          {footer && <div className="mt-1.5 border-t border-hairline pt-1.5 text-ink-2">{footer}</div>}
          {hint && <div className="mt-1.5 text-[11.5px] text-muted">{hint}</div>}
        </div>,
        document.body,
      )}
    </>
  );
}
