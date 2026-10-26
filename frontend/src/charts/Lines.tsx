/** Lines over a shared x axis, read with a crosshair.
 *
 * A series stops where its data stops: a `null` breaks the line, it is
 * never bridged or padded (a year that had not started reads as no data,
 * not as "spent nothing"). Hover, or a finger sliding sideways, walks the
 * points; the card lists every visible series at that x. */
import { area as d3area, curveMonotoneX, curveStepAfter, line as d3line } from "d3-shape";
import { AnimatePresence, motion } from "motion/react";
import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { compact } from "@/lib/format";
import { useWidth } from "@/lib/hooks";

import { axisScale, ticks as tickValues } from "./scale";
import { ChartTip, type TipRow } from "./Tooltip";

export interface LineSeries {
  key: string;
  name: string;
  color: string;
  values: (number | null)[];
  dash?: boolean;
  width?: number;
  area?: boolean;
  faint?: boolean;
  step?: boolean;
  /** Not in the tooltip (a faint raw line behind its smoothed twin). */
  silent?: boolean;
  /** A layer of a stack: filled solid down to these values (the layer
   * under it) instead of to the axis. `values` are then the running top. */
  fillTo?: (number | null)[];
}

export interface Marker { index: number; series: string; label: string; anchor?: "start" | "middle" | "end" }
export interface RefLine { value: number; color: string; label?: string; dash?: boolean }

const PAD = { top: 14, bottom: 26 };

export function Lines({
  xs, series, height = 240, format = compact, tipFormat, xLabel, xTicks, zero = true,
  clamp, markers = [], refs = [], band, endLabels = false, ariaLabel, onPick, pickHint,
  todayIndex, tipExtra, rightPad, yLog = false,
}: {
  /** One x per point: a timestamp or an index -- spacing follows it. */
  xs: number[];
  series: LineSeries[];
  height?: number;
  format?: (v: number) => string;
  tipFormat?: (v: number, s: LineSeries) => string;
  xLabel: (i: number) => string;
  /** Axis labels: which indices, and what to print. */
  xTicks: { index: number; label: string }[] | ((plotWidth: number) => { index: number; label: string }[]);
  zero?: boolean;
  /** Keep the axis inside [lo, hi]: a point beyond is drawn on the edge. */
  clamp?: [number, number];
  markers?: Marker[];
  refs?: RefLine[];
  band?: { low: (number | null)[]; high: (number | null)[]; color: string };
  endLabels?: boolean;
  ariaLabel: string;
  onPick?: (i: number) => void;
  pickHint?: string;
  /** A vertical rule: where the observed past ends and the projection starts. */
  todayIndex?: number;
  tipExtra?: (i: number) => TipRow[];
  rightPad?: number;
  /** A log axis: a multi-decade horizon needs it. */
  yLog?: boolean;
}) {
  const [box, width] = useWidth<HTMLDivElement>();
  const grad = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);
  const dragging = useRef(false);

  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (band) values.push(...band.low.filter((v): v is number => v != null), ...band.high.filter((v): v is number => v != null));
  refs.forEach((r) => values.push(r.value));
  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (clamp) { lo = Math.max(clamp[0], lo); hi = Math.min(clamp[1], hi); }
  // Log only while every drawn value is positive; otherwise linear, and the
  // caller says so (`logApplied`).
  const log = yLog && lo > 0;
  const [bottom, top, step] = log ? [lo, hi > lo ? hi : lo * 10, 0] : axisScale(lo, hi, { zero, min: 3, max: 5 });
  const ticks = log ? logTicks(bottom, top) : tickValues(bottom, top, step);
  const padLeft = Math.max(30, Math.max(...ticks.map((t) => format(t).length)) * 6.6 + 10);
  // On a phone the names would eat a third of the plot: the legend or the
  // cards under the chart say them instead.
  const showEnds = endLabels && width >= 520;
  const longestName = showEnds ? Math.min(16, Math.max(0, ...series.filter((s) => !s.faint).map((s) => s.name.length))) : 0;
  const padRight = rightPad ?? (showEnds ? Math.min(110, longestName * 6.4 + 14) : 8);
  const plotW = Math.max(0, width - padLeft - padRight);
  const plotH = height - PAD.top - PAD.bottom;
  const x0 = xs[0] ?? 0;
  const x1 = xs[xs.length - 1] ?? 1;
  const xAt = (v: number) => padLeft + (x1 === x0 ? plotW / 2 : ((v - x0) / (x1 - x0)) * plotW);
  const yAt = (v: number) => {
    const kept = clamp ? Math.min(Math.max(v, clamp[0]), clamp[1]) : v;
    if (log) {
      return PAD.top + plotH * (1 - (Math.log(Math.max(kept, bottom)) - Math.log(bottom)) / (Math.log(top) - Math.log(bottom) || 1));
    }
    return PAD.top + plotH * (1 - (kept - bottom) / (top - bottom || 1));
  };

  const paths = useMemo(() => series.map((s) => {
    const pts = s.values.map((v, i) => [xs[i], v] as const);
    const gen = d3line<readonly [number, number | null]>()
      .defined((p) => p[1] != null)
      .x((p) => xAt(p[0]))
      .y((p) => yAt(p[1] as number))
      .curve(s.step ? curveStepAfter : curveMonotoneX);
    const fill = s.fillTo
      ? d3area<readonly [number, number | null, number | null]>()
        .defined((p) => p[1] != null && p[2] != null)
        .x((p) => xAt(p[0]))
        .y0((p) => yAt(p[2] as number))
        .y1((p) => yAt(p[1] as number))
        .curve(s.step ? curveStepAfter : curveMonotoneX)(s.values.map((v, i) => [xs[i], v, s.fillTo![i]] as const))
      : s.area
      ? d3area<readonly [number, number | null]>()
        .defined((p) => p[1] != null)
        .x((p) => xAt(p[0]))
        .y0(yAt(Math.max(bottom, Math.min(0, top))))
        .y1((p) => yAt(p[1] as number))
        .curve(s.step ? curveStepAfter : curveMonotoneX)(pts)
      : null;
    return { line: gen(pts) ?? "", fill };
  }), [series, xs, width, bottom, top]); // eslint-disable-line react-hooks/exhaustive-deps

  const bandPath = useMemo(() => {
    if (!band) return null;
    const pts = xs.map((x, i) => [x, band.low[i], band.high[i]] as const);
    return d3area<readonly [number, number | null, number | null]>()
      .defined((p) => p[1] != null && p[2] != null)
      .x((p) => xAt(p[0]))
      .y0((p) => yAt(p[1] as number))
      .y1((p) => yAt(p[2] as number))
      .curve(curveMonotoneX)(pts);
  }, [band, xs, width, bottom, top]); // eslint-disable-line react-hooks/exhaustive-deps

  const nearest = (clientX: number, svg: SVGSVGElement) => {
    const px = clientX - svg.getBoundingClientRect().left;
    let best = 0;
    let dist = Infinity;
    xs.forEach((x, i) => {
      const d = Math.abs(xAt(x) - px);
      if (d < dist) { dist = d; best = i; }
    });
    return best;
  };

  const move = (e: PointerEvent<SVGRectElement>) => {
    if (e.pointerType !== "mouse" && !dragging.current) return;
    setHover(nearest(e.clientX, e.currentTarget.ownerSVGElement!));
  };
  const down = (e: PointerEvent<SVGRectElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    setHover(nearest(e.clientX, e.currentTarget.ownerSVGElement!));
  };
  const up = (e: PointerEvent<SVGRectElement>) => {
    dragging.current = false;
    if (e.pointerType === "mouse" && onPick && hover != null) onPick(hover);
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      e.stopPropagation();
      const d = e.key === "ArrowRight" ? 1 : -1;
      setHover((h) => Math.max(0, Math.min(xs.length - 1, (h ?? (d > 0 ? -1 : xs.length)) + d)));
    } else if (e.key === "Escape") setHover(null);
    else if (e.key === "Enter" && hover != null) onPick?.(hover);
  };

  // End labels, pushed apart so two lines ending close do not overprint.
  const ends = useMemo(() => {
    if (!showEnds) return [];
    const out = series.filter((s) => !s.faint).map((s) => {
      let i = s.values.length - 1;
      while (i >= 0 && s.values[i] == null) i--;
      return i < 0 ? null : { s, i, y: yAt(s.values[i] as number) };
    }).filter(Boolean) as { s: LineSeries; i: number; y: number }[];
    out.sort((a, b) => a.y - b.y);
    let floor = -Infinity;
    for (const e of out) { e.y = Math.max(e.y, floor + 13); floor = e.y; }
    return out;
  }, [series, showEnds, width, bottom, top]); // eslint-disable-line react-hooks/exhaustive-deps

  const tipRows: TipRow[] = hover == null ? [] : [
    ...series.filter((s) => !s.silent && s.values[hover] != null).map((s) => ({
      name: s.name,
      value: (tipFormat ?? ((v: number) => format(v)))(s.values[hover] as number, s),
      color: s.color,
      dashed: s.dash,
    })),
    ...(tipExtra ? tipExtra(hover) : []),
  ];
  const hx = hover != null ? xAt(xs[hover]) : 0;
  const firstY = hover != null
    ? Math.min(...series.filter((s) => s.values[hover] != null).map((s) => yAt(s.values[hover] as number)), height)
    : 0;

  return (
    <div ref={box} className="relative w-full select-none" style={{ height }}>
      {width > 0 && xs.length > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} tabIndex={0}
             className="block touch-pan-y overflow-visible outline-none" onKeyDown={key}
             onBlur={() => setHover(null)}>
          <defs>
            {series.filter((s) => s.area).map((s) => (
              <linearGradient key={s.key} id={`${grad}-${s.key}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.22} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0.01} />
              </linearGradient>
            ))}
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padLeft} x2={width - padRight} y1={yAt(t)} y2={yAt(t)}
                    stroke={t === 0 && bottom < 0 ? "var(--axis)" : t === bottom ? "var(--axis)" : "var(--grid)"}
                    strokeDasharray={t === bottom || t === 0 ? undefined : "2 4"} />
              <text x={padLeft - 8} y={yAt(t) + 4} textAnchor="end" className="fill-muted text-[11px] num">{format(t)}</text>
            </g>
          ))}
          {(typeof xTicks === "function" ? xTicks(plotW) : xTicks).map((t) => (
            <text key={`${t.index}-${t.label}`} x={xAt(xs[t.index])} y={height - 7}
                  textAnchor={t.index === 0 ? "start" : t.index === xs.length - 1 ? "end" : "middle"}
                  className="fill-muted text-[11px] num">{t.label}</text>
          ))}
          {todayIndex != null && xs[todayIndex] != null && (
            <g>
              <line x1={xAt(xs[todayIndex])} x2={xAt(xs[todayIndex])} y1={PAD.top} y2={PAD.top + plotH}
                    stroke="var(--axis)" strokeDasharray="3 3" />
              <text x={xAt(xs[todayIndex]) + 6} y={PAD.top + 10} className="fill-muted text-[11px]">aujourd'hui</text>
            </g>
          )}
          {bandPath && <path d={bandPath} fill={band!.color} opacity={0.12} />}
          {refs.map((r, i) => (
            <g key={i}>
              <line x1={padLeft} x2={width - padRight} y1={yAt(r.value)} y2={yAt(r.value)}
                    stroke={r.color} strokeDasharray={r.dash === false ? undefined : "5 4"} strokeOpacity={0.7} />
              {r.label && <text x={width - padRight} y={yAt(r.value) - 5} textAnchor="end"
                                className="text-[10.5px] font-medium" fill={r.color}>{r.label}</text>}
            </g>
          ))}
          {series.map((s, i) => (
            <g key={`${s.key}-${s.values.length}`}>
              {paths[i].fill && (
                <motion.path d={paths[i].fill!} fill={s.fillTo ? s.color : `url(#${grad}-${s.key})`}
                             fillOpacity={s.fillTo ? (s.dash ? 0.32 : 0.55) : undefined}
                             initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }} />
              )}
              <motion.path
                d={paths[i].line}
                fill="none"
                stroke={s.color}
                strokeWidth={s.width ?? (s.faint ? 1.25 : 2)}
                strokeOpacity={s.faint ? 0.35 : 1}
                strokeDasharray={s.dash ? "5 4" : undefined}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={s.dash ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
                animate={s.dash ? { opacity: 1 } : { pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
              />
            </g>
          ))}
          {markers.map((m) => {
            const s = series.find((x) => x.key === m.series);
            const v = s?.values[m.index];
            if (!s || v == null) return null;
            const mx = xAt(xs[m.index]);
            const my = yAt(v);
            const anchor = m.anchor ?? (mx > width - 120 ? "end" : mx < padLeft + 60 ? "start" : "middle");
            return (
              <g key={`${m.series}-${m.index}`}>
                <circle cx={mx} cy={my} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                {m.label && <text x={mx} y={my - 10} textAnchor={anchor} className="fill-ink-2 text-[11px] font-medium num"
                      paintOrder="stroke" stroke="var(--surface)" strokeWidth={3}>{m.label}</text>}
              </g>
            );
          })}
          {ends.map((e) => (
            <text key={e.s.key} x={width - padRight + 8} y={e.y + 4} className="text-[11px] font-semibold"
                  fill={e.s.color}>
              <title>{e.s.name}</title>
              {e.s.name.length > 16 ? `${e.s.name.slice(0, 15)}…` : e.s.name}
            </text>
          ))}
          {hover != null && (
            <g pointerEvents="none">
              <line x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + plotH} stroke="var(--ink-2)" strokeOpacity={0.35} />
              {series.filter((s) => !s.faint && s.values[hover] != null).map((s) => (
                <circle key={s.key} cx={hx} cy={yAt(s.values[hover] as number)} r={4.5} fill={s.color}
                        stroke="var(--surface)" strokeWidth={2} />
              ))}
            </g>
          )}
          <rect x={padLeft} y={PAD.top} width={plotW} height={plotH} fill="transparent"
                className={onPick ? "cursor-pointer" : "cursor-crosshair"}
                onPointerMove={move} onPointerDown={down} onPointerUp={up}
                onPointerCancel={() => { dragging.current = false; }}
                onPointerLeave={(e) => { if (e.pointerType === "mouse") setHover(null); }} />
        </svg>
      )}
      <AnimatePresence>
        {hover != null && tipRows.length > 0 && (
          <motion.div key="tip" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.1 }}>
            <ChartTip x={hx} y={firstY - 20} width={width}
                      title={xLabel(hover)} rows={tipRows} hint={onPick ? pickHint : undefined} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Up to `count` evenly spaced axis labels, the ends pinned. */
export function spreadTicks(n: number, width: number, label: (i: number) => string, minGap = 70): { index: number; label: string }[] {
  if (n <= 0) return [];
  if (n === 1) return [{ index: 0, label: label(0) }];
  const slots = Math.max(2, Math.min(n, Math.floor(width / minGap)));
  const out: { index: number; label: string }[] = [];
  for (let k = 0; k < slots; k++) {
    const index = Math.round((k * (n - 1)) / (slots - 1));
    const text = label(index);
    // Two points can share a label (the month measured and the same month
    // projected): one tick, not two printed on top of each other.
    if (!out.length || (out[out.length - 1].index !== index && out[out.length - 1].label !== text)) {
      out.push({ index, label: text });
    }
  }
  return out;
}

/** Tick values on a 1-2-5 x 10^k grid inside [lo, hi], at most five; the
 * ends themselves when the range falls between two grid values. */
function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); 10 ** e <= hi; e++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      if (v >= lo && v <= hi) out.push(v);
    }
  }
  if (out.length < 2) return [lo, hi];
  if (out.length <= 5) return out;
  const step = (out.length - 1) / 4;
  return [0, 1, 2, 3, 4].map((i) => out[Math.round(i * step)]);
}

/** Axis labels at the first point of each month of a time axis, thinned
 * so two never sit closer than `minGap` pixels. */
export function monthTicks(xs: number[], plotWidth: number, minGap = 64): { index: number; label: string }[] {
  if (xs.length < 2) return [];
  const span = xs[xs.length - 1] - xs[0] || 1;
  const short = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const out: { index: number; label: string; px: number }[] = [];
  let previous = -1;
  xs.forEach((x, i) => {
    const d = new Date(x);
    const key = d.getFullYear() * 12 + d.getMonth();
    if (key === previous) return;
    previous = key;
    const px = ((x - xs[0]) / span) * plotWidth;
    if (out.length && px - out[out.length - 1].px < minGap) return;
    out.push({ index: i, label: `${short[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`, px });
  });
  return out;
}
