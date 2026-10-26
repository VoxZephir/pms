/** Spending day by day, on a sequential ramp: the darker, the more spent --
 * in both themes. A day without spending is drawn hollow, never grey: a grey
 * cell would read as the busiest day on a dark background.
 *
 * Wide: one strip per year, weeks across (the shape of a year at a glance).
 * Narrow: one small month calendar per month, three across -- a 53-week strip
 * on a phone would be 6-pixel cells nobody can tap. */
import { useMemo, useState } from "react";

import { cx } from "@/components/ui";
import { MONTHS, MONTHS_SHORT, WEEKDAYS_SHORT, chf, day as parseDay, frLongDay, iso } from "@/lib/format";
import { useWidth } from "@/lib/hooks";

import { levelOf, quantileCuts } from "./scale";

type Daily = Record<string, [number, number]>;

export function CalendarHeat({
  daily, start, end, onPick,
}: { daily: Daily; start: string; end: string; onPick?: (iso: string) => void }) {
  const [box, width] = useWidth<HTMLDivElement>();
  const [focus, setFocus] = useState<string | null>(null);
  const cuts = useMemo(() => quantileCuts(Object.values(daily).map((d) => d[0])), [daily]);
  const days = useMemo(() => {
    const out: string[] = [];
    const d = parseDay(start);
    const last = parseDay(end);
    while (d <= last) { out.push(iso(d)); d.setDate(d.getDate() + 1); }
    return out;
  }, [start, end]);

  // A strip needs both room (11 px a week at least) and a long enough window:
  // three months in a year-wide strip would fill a quarter of it.
  const weeks = Math.min(53, Math.ceil(days.length / 7) + 1);
  const pitchWide = Math.min(18, (width - 28) / weeks);
  const wide = pitchWide >= 11 && days.length > 120;
  const info = focus ? daily[focus] : null;

  const cell = (dayIso: string, size: number, x: number, y: number) => {
    const v = daily[dayIso];
    const level = levelOf(v?.[0] ?? 0, cuts);
    const label = `${frLongDay(dayIso)} : ${chf(v?.[0] ?? 0)} CHF${v ? `, ${v[1]} transaction${v[1] > 1 ? "s" : ""}` : ""}`;
    return (
      <rect
        key={dayIso}
        x={x} y={y} width={size} height={size} rx={Math.min(3, size / 4)}
        fill={level ? `var(--h${level})` : "transparent"}
        stroke={level ? (focus === dayIso ? "var(--ink)" : "none") : "var(--axis)"}
        strokeWidth={focus === dayIso ? 1.5 : 1}
        className={onPick ? "cursor-pointer" : undefined}
        role={onPick ? "button" : undefined}
        tabIndex={onPick ? 0 : undefined}
        aria-label={label}
        onPointerEnter={(e) => e.pointerType === "mouse" && setFocus(dayIso)}
        onFocus={() => setFocus(dayIso)}
        onClick={() => onPick?.(dayIso)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick?.(dayIso); } }}
      />
    );
  };

  return (
    <div ref={box} className="w-full" onPointerLeave={() => setFocus(null)}>
      {width > 0 && wide && <YearStrips days={days} pitch={pitchWide} cell={cell} />}
      {width > 0 && !wide && <MonthGrids days={days} width={width} cell={cell} />}
      <div className="mt-3 flex min-h-[20px] flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
        <span className="flex items-center gap-1.5">
          moins
          {[0, 1, 2, 3, 4, 5].map((l) => (
            <i key={l} className="inline-block size-3 rounded-[3px]"
               style={l ? { background: `var(--h${l})` } : { boxShadow: "inset 0 0 0 1px var(--axis)" }} />
          ))}
          plus
        </span>
        {focus ? (
          <span className="num text-ink-2">
            <b className="font-semibold text-ink">{frLongDay(focus)}</b> · {chf(info?.[0] ?? 0)} CHF
            {info ? ` · ${info[1]} transaction${info[1] > 1 ? "s" : ""}` : " · rien dépensé"}
          </span>
        ) : cuts.length > 0 && (
          <span className="num">seuils : {cuts.map((c) => chf(c, 0)).join(" · ")} CHF</span>
        )}
      </div>
    </div>
  );
}

type CellFn = (dayIso: string, size: number, x: number, y: number) => React.ReactNode;

/** A window of a year or less is one continuous strip -- twelve rolling
 * months should not break at the 31st of December. Longer windows get one
 * strip per calendar year. */
function YearStrips({ days, pitch, cell }: { days: string[]; pitch: number; cell: CellFn }) {
  const strips = useMemo(() => {
    if (days.length <= 371) return [days];
    const by = new Map<string, string[]>();
    days.forEach((d) => {
      const y = d.slice(0, 4);
      if (!by.has(y)) by.set(y, []);
      by.get(y)!.push(d);
    });
    return [...by.values()];
  }, [days]);
  const size = pitch - 2.5;
  const label = 26;
  return (
    <div className="space-y-4">
      {strips.map((list) => {
        const first = parseDay(list[0]);
        const origin = new Date(first);
        origin.setDate(first.getDate() - ((first.getDay() + 6) % 7));
        const months: { x: number; label: string }[] = [];
        const rects = list.map((d) => {
          const date = parseDay(d);
          const index = Math.round((date.getTime() - origin.getTime()) / 86_400_000);
          const col = Math.floor(index / 7);
          const row = index % 7;
          if (date.getDate() === 1 || d === list[0]) {
            months.push({ x: label + col * pitch, label: MONTHS_SHORT[date.getMonth()] });
          }
          return cell(d, size, label + col * pitch, row * pitch);
        });
        // The first label is dropped when the next month starts a week later:
        // two labels would overprint.
        if (months.length > 1 && months[1].x - months[0].x < 30) months.shift();
        const h = 7 * pitch + 16;
        const y0 = list[0].slice(0, 4);
        const y1 = list[list.length - 1].slice(0, 4);
        return (
          <div key={list[0]}>
            <div className="mb-1 text-[12px] font-semibold text-ink-2 num">{y0 === y1 ? y0 : `${y0} – ${y1}`}</div>
            <svg width={label + weeksOf(list, origin) * pitch + 2} height={h} className="block overflow-visible">
              {[0, 2, 4].map((r) => (
                <text key={r} x={0} y={r * pitch + size - 1} className="fill-muted text-[10.5px]">{WEEKDAYS_SHORT[r]}</text>
              ))}
              {rects}
              {months.map((m) => (
                <text key={`${m.x}-${m.label}`} x={m.x} y={h - 2} className="fill-muted text-[10.5px]">{m.label}</text>
              ))}
            </svg>
          </div>
        );
      })}
    </div>
  );
}

function weeksOf(list: string[], origin: Date): number {
  const last = parseDay(list[list.length - 1]);
  return Math.floor(Math.round((last.getTime() - origin.getTime()) / 86_400_000) / 7) + 1;
}

function MonthGrids({ days, width, cell }: { days: string[]; width: number; cell: CellFn }) {
  const months = useMemo(() => {
    const by = new Map<string, string[]>();
    days.forEach((d) => {
      const k = d.slice(0, 7);
      if (!by.has(k)) by.set(k, []);
      by.get(k)!.push(d);
    });
    return [...by.entries()];
  }, [days]);
  // As many columns as there are months, up to what the width holds: one
  // month used to sit in a third of the card with 14-pixel cells, too small
  // to tap; alone it takes the width, with cells a finger can hit.
  const cols = Math.max(1, Math.min(months.length, width >= 900 ? 6 : width >= 520 ? 4 : 3));
  const gap = 14;
  const pitch = Math.min(cols <= 2 ? 44 : 30, (width - gap * (cols - 1)) / cols / 7);
  const monthW = pitch * 7;
  const size = pitch - 2;
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${cols}, ${monthW}px)`, gap }}>
      {months.map(([key, list]) => {
        const [y, m] = key.split("-").map(Number);
        const first = new Date(y, m - 1, 1);
        const offset = (first.getDay() + 6) % 7;
        const rows = Math.ceil((offset + new Date(y, m, 0).getDate()) / 7);
        return (
          <div key={key}>
            <div className={cx("mb-1 text-[11.5px] font-semibold capitalize text-ink-2")}>
              {MONTHS[m - 1]} {y !== new Date().getFullYear() ? String(y).slice(2) : ""}
            </div>
            <svg width={monthW} height={rows * pitch} className="block overflow-visible">
              {list.map((d) => {
                const i = offset + parseDay(d).getDate() - 1;
                return cell(d, size, (i % 7) * pitch, Math.floor(i / 7) * pitch);
              })}
            </svg>
          </div>
        );
      })}
    </div>
  );
}
