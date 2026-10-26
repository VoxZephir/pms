/** Stacked columns, laid out at the width they get.
 *
 * One gesture vocabulary for mouse, pen and finger (pointer events):
 * hover or a first tap shows a column's figures; a click, or a second tap on
 * the same column, opens it (`onPick`); dragging sideways selects a range of
 * columns (`onBrush`). Vertical swipes stay the page's: `touch-action: pan-y`.
 * Arrow keys walk the columns, Enter opens one. */
import { AnimatePresence, motion } from "motion/react";
import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { cx } from "@/components/ui";
import { compact } from "@/lib/format";
import { useWidth } from "@/lib/hooks";

import { axisScale, labelEvery, ticks as tickValues } from "./scale";
import { ChartTip, type TipRow } from "./Tooltip";

export interface Segment { name: string; value: number; color: string }
export interface Column {
  key: string;
  label: string;
  short?: string;
  segments: Segment[];
  total: number;
  marker?: number;
  pickable?: boolean;
  /** Draw hollow: a period with nothing in it is unmistakably empty. */
  hollow?: boolean;
}

const PAD = { top: 12, right: 6, bottom: 26 };
const SPRING = { type: "spring", stiffness: 260, damping: 30, mass: 0.8 } as const;

export function Columns({
  columns, height = 280, format = compact, tipRows, tipFooter, pickHint, onPick, onBrush,
  ariaLabel, markerColor = "var(--good)", reference, referenceLabel, fixedMax, children,
  stackOrder = "value",
}: {
  /** "value": the largest slice at the bottom (a breakdown); "given": the
   * order the segments come in (a floor under a remainder). */
  stackOrder?: "value" | "given";
  columns: Column[];
  height?: number;
  format?: (v: number) => string;
  tipRows?: (c: Column) => TipRow[];
  tipFooter?: (c: Column) => ReactNode;
  pickHint?: string;
  onPick?: (c: Column, index: number) => void;
  onBrush?: (from: number, to: number) => void;
  ariaLabel: string;
  markerColor?: string;
  /** A horizontal rule: a median, a floor, a budget. */
  reference?: number;
  referenceLabel?: string;
  /** Scale every column to this top (shares: 100). */
  fixedMax?: number;
  children?: ReactNode;
}) {
  const [box, width] = useWidth<HTMLDivElement>();
  const clip = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);
  const [brush, setBrush] = useState<[number, number] | null>(null);
  const drag = useRef<{ x: number; index: number; type: string; moved: boolean } | null>(null);
  const tapped = useRef<number | null>(null);

  const n = columns.length;
  const max = fixedMax ?? Math.max(1, ...columns.map((c) => Math.max(c.total, c.marker ?? 0)), reference ?? 0);
  const [, top, step] = axisScale(0, max, { zero: true, min: 3, max: 4 });
  const ticks = tickValues(0, top, step);
  const padLeft = Math.max(30, Math.max(...ticks.map((t) => format(t).length)) * 6.6 + 10);
  const plotW = Math.max(0, width - padLeft - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const band = n ? plotW / n : 0;
  const barW = Math.max(1, Math.min(30, band * (band > 14 ? 0.62 : 0.78)));
  const y = (v: number) => PAD.top + plotH * (1 - v / top);
  const every = labelEvery(n, plotW, 54);
  const rounded = barW >= 6;

  const layout = useMemo(() => columns.map((c, i) => {
    const x = padLeft + band * i + (band - barW) / 2;
    let acc = 0;
    const kept = c.segments.filter((s) => s.value > 0);
    const ordered = stackOrder === "value" ? [...kept].sort((a, b) => b.value - a.value) : kept;
    const segs = ordered.map((s) => {
      const y1 = y(acc + s.value);
      const y0 = y(acc);
      acc += s.value;
      return { ...s, y: y1, h: Math.max(0.6, y0 - y1 - (barW > 3 ? 1.25 : 0)) };
    });
    return { x, segs, topY: y(c.total) };
  }), [columns, padLeft, band, barW, top, plotH, stackOrder]); // eslint-disable-line react-hooks/exhaustive-deps

  const indexAt = (clientX: number, target: Element) => {
    const rect = target.getBoundingClientRect();
    const px = clientX - rect.left - padLeft;
    return Math.max(0, Math.min(n - 1, Math.floor(px / band)));
  };

  const down = (e: PointerEvent<SVGRectElement>) => {
    const index = indexAt(e.clientX, e.currentTarget.ownerSVGElement!);
    drag.current = { x: e.clientX, index, type: e.pointerType, moved: false };
    if (onBrush) e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent<SVGRectElement>) => {
    const index = indexAt(e.clientX, e.currentTarget.ownerSVGElement!);
    const d = drag.current;
    if (d && onBrush && Math.abs(e.clientX - d.x) > 8) {
      d.moved = true;
      setBrush([Math.min(d.index, index), Math.max(d.index, index)]);
      setHover(null);
      return;
    }
    if (e.pointerType === "mouse" || d) setHover(index);
  };
  const up = (e: PointerEvent<SVGRectElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    const index = indexAt(e.clientX, e.currentTarget.ownerSVGElement!);
    if (d.moved && brush) {
      const [a, b] = brush;
      setBrush(null);
      if (b > a) onBrush?.(a, b);
      return;
    }
    setBrush(null);
    const col = columns[index];
    const pickable = onPick && col && col.pickable !== false;
    if (d.type === "mouse") {
      if (pickable) onPick(col, index);
      return;
    }
    // A finger: the first tap reads, the second on the same column opens.
    if (tapped.current === index && pickable) {
      tapped.current = null;
      onPick(col, index);
    } else {
      tapped.current = index;
      setHover(index);
    }
  };

  const key = (e: KeyboardEvent) => {
    if (!n) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      e.stopPropagation();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      setHover((h) => Math.max(0, Math.min(n - 1, (h ?? (delta > 0 ? -1 : n)) + delta)));
    } else if (e.key === "Enter" && hover != null && onPick && columns[hover]?.pickable !== false) {
      onPick(columns[hover], hover);
    } else if (e.key === "Escape") {
      setHover(null);
    }
  };

  const active = hover != null ? columns[hover] : null;
  const activeLayout = hover != null ? layout[hover] : null;

  return (
    <div ref={box} className="relative w-full select-none" style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          className="block touch-pan-y overflow-visible outline-none"
          role="img"
          aria-label={ariaLabel}
          tabIndex={0}
          onKeyDown={key}
          onBlur={() => setHover(null)}
        >
          {rounded && (
            <defs>
              {layout.map((l, i) => (
                <clipPath key={columns[i].key} id={`${clip}-${i}`}>
                  <motion.rect x={l.x} width={barW} rx={Math.min(5, barW / 3)}
                               initial={{ y: PAD.top + plotH, height: 0 }}
                               animate={{ y: l.topY, height: PAD.top + plotH - l.topY + 6 }}
                               transition={SPRING} />
                </clipPath>
              ))}
            </defs>
          )}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padLeft} x2={width - PAD.right} y1={y(t)} y2={y(t)}
                    stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1}
                    strokeDasharray={t === 0 ? undefined : "2 4"} />
              <text x={padLeft - 8} y={y(t) + 4} textAnchor="end"
                    className="fill-muted text-[11px] num">{format(t)}</text>
            </g>
          ))}

          {hover != null && activeLayout && (
            <rect x={padLeft + band * hover + 1} y={PAD.top - 4} width={Math.max(1, band - 2)}
                  height={plotH + 4} rx={8} fill="var(--surface-2)" />
          )}
          {brush && (
            <rect x={padLeft + band * brush[0]} y={PAD.top - 4} width={band * (brush[1] - brush[0] + 1)}
                  height={plotH + 4} rx={8} fill="color-mix(in srgb, var(--s0) 14%, transparent)"
                  stroke="var(--s0)" strokeOpacity={0.5} />
          )}

          {layout.map((l, i) => {
            const c = columns[i];
            const dim = hover != null && hover !== i;
            return (
              <g key={c.key} clipPath={rounded ? `url(#${clip}-${i})` : undefined}
                 style={{ opacity: dim ? 0.55 : 1, transition: "opacity .15s" }}>
                {c.hollow && (
                  <rect x={l.x + 0.5} y={PAD.top + 0.5} width={Math.max(0, barW - 1)} height={plotH - 1}
                        fill="none" stroke="var(--axis)" strokeDasharray="3 3" />
                )}
                {l.segs.map((s) => (
                  <motion.rect key={s.name} x={l.x} width={barW} fill={s.color}
                               initial={{ y: PAD.top + plotH, height: 0 }}
                               animate={{ y: s.y, height: s.h }}
                               transition={SPRING} />
                ))}
              </g>
            );
          })}

          {layout.map((l, i) => {
            const m = columns[i].marker;
            if (!m || m <= 0) return null;
            return (
              <motion.line key={`m-${columns[i].key}`} x1={l.x - 3} x2={l.x + barW + 3}
                           initial={false} animate={{ y1: y(m), y2: y(m) }} transition={SPRING}
                           stroke={markerColor} strokeWidth={2.25} strokeLinecap="round" />
            );
          })}

          {reference != null && reference > 0 && reference <= top && (
            <g>
              <line x1={padLeft} x2={width - PAD.right} y1={y(reference)} y2={y(reference)}
                    stroke="var(--ink-2)" strokeDasharray="5 4" strokeWidth={1.25} />
              {referenceLabel && (
                <text x={width - PAD.right} y={y(reference) - 6} textAnchor="end"
                      className="fill-ink-2 text-[11px] font-medium">{referenceLabel}</text>
              )}
            </g>
          )}

          {columns.map((c, i) => (i % every === 0 ? (
            <text key={`x-${c.key}`} x={padLeft + band * i + band / 2} y={height - 7} textAnchor="middle"
                  className={cx("text-[11px] num", hover === i ? "fill-ink font-semibold" : "fill-muted")}>
              {c.short ?? c.label}
            </text>
          ) : null))}

          <rect x={padLeft} y={PAD.top - 4} width={plotW} height={plotH + PAD.bottom}
                fill="transparent" className={onPick ? "cursor-pointer" : undefined}
                onPointerDown={down} onPointerMove={move} onPointerUp={up}
                onPointerCancel={() => { drag.current = null; setBrush(null); }}
                onPointerLeave={(e) => { if (e.pointerType === "mouse" && !drag.current) setHover(null); }} />
          {children}
        </svg>
      )}
      <AnimatePresence>
        {active && activeLayout && (
          <motion.div key="tip" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      transition={{ duration: 0.1 }}>
            <ChartTip
              x={activeLayout.x + barW / 2}
              y={activeLayout.topY - 8}
              width={width}
              title={active.label}
              rows={tipRows ? tipRows(active) : active.segments.filter((s) => s.value > 0)
                .sort((a, b) => b.value - a.value)
                .map((s) => ({ name: s.name, value: format(s.value), color: s.color }))}
              footer={tipFooter?.(active)}
              hint={onPick && active.pickable !== false ? pickHint : undefined}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
