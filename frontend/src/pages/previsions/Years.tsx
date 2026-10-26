/** The barème year by year: one rate per calendar year of the horizon,
 * drawn as bars to drag (mouse, pen), to tap for a selection (a finger),
 * or to nudge with the arrow keys, and typed to the hundredth in the grid
 * below. The server reads the years off the barème (`plans.rate_years`)
 * and turns the typed ones back into periods; this file only edits. */
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Input } from "@/components/Form";
import { Button, cx } from "@/components/ui";
import { planAction, type GrowthPath, type Previsions, type RateYear } from "@/lib/previsions";

import { useAction } from "./Plan";

/** What the rate panel edits: the common barème, or one pocket's. */
export interface RateTarget {
  pocket: string | null; label: string; own: boolean;
  segments: [number, number][]; years: RateYear[];
  vol: number | null; volMeasured: number | null; growth: GrowthPath;
}

/** The fields a rate edit posts to reach its target. */
export const targetOf = (t: RateTarget) => (t.pocket ? { rate_pocket: t.pocket } : {});

const LIMIT = 50;
/** A rate typed the French way ("5,25", "−3 %"), in percent; null when blank or not a number. */
export const percentOf = (text: string): number | null => {
  const c = text.replace(/[\s%]/g, "").replace("−", "-").replace(",", ".");
  if (c === "" || c === "-" || c === ".") return null;
  const n = Number(c);
  return Number.isFinite(n) ? n : null;
};
const textOf = (rate: number | null) => (rate == null ? "" : String(Math.round(rate * 10000) / 100).replace(".", ","));
const shown = (p: number) => `${p > 0 ? "+" : p < 0 ? "−" : ""}${String(Math.round(Math.abs(p) * 100) / 100).replace(".", ",")} %`;
const clamp = (p: number) => Math.max(-LIMIT, Math.min(LIMIT, Math.round(p * 100) / 100));

/** The bars: one per year, from the zero line. The scale holds still
 * while a bar is dragged, so the bar stays under the pointer. */
function Bars({ years, values, selected, onPaint, onSelect }: {
  years: RateYear[]; values: (number | null)[]; selected: Set<number>;
  onPaint: (i: number, p: number) => void; onSelect: (i: number, extend: boolean) => void;
}) {
  const H = 168;
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ hi: number; lo: number; x: number; y: number; moved: boolean; touch: boolean; i: number } | null>(null);
  const known = values.filter((v): v is number => v != null);
  // Room above the highest bar and below the lowest for its figure.
  const live = { hi: Math.max(10, Math.ceil((Math.max(0, ...known) + 2) / 5) * 5),
                 lo: Math.min(-5, Math.floor((Math.min(0, ...known) - 3) / 5) * 5) };
  const { hi, lo } = drag.current ?? live;
  const y = (p: number) => ((hi - p) / (hi - lo)) * H;
  const zero = y(0);
  const many = years.length > 12;

  const at = (e: PointerEvent) => {
    const r = box.current!.getBoundingClientRect();
    const i = Math.max(0, Math.min(years.length - 1, Math.floor(((e.clientX - r.left) / r.width) * years.length)));
    const s = drag.current ?? live;
    const p = s.hi - ((e.clientY - r.top) / H) * (s.hi - s.lo);
    // A drag sets tenths; the grid takes hundredths.
    return { i, p: Math.max(-LIMIT, Math.min(LIMIT, Math.round(p * 10) / 10)) };
  };
  const down = (e: PointerEvent) => {
    const touch = e.pointerType === "touch";
    drag.current = { ...live, x: e.clientX, y: e.clientY, moved: false, touch, i: at(e).i };
    // A finger scrolls the page and taps to select; a mouse or a pen draws.
    if (!touch) e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => {
    const s = drag.current;
    if (!s || s.touch) return;
    if (!s.moved && Math.hypot(e.clientX - s.x, e.clientY - s.y) < 4) return;
    s.moved = true;
    const { i, p } = at(e);
    onPaint(i, p);
  };
  const up = (e: PointerEvent) => {
    const s = drag.current;
    drag.current = null;
    if (s && !s.moved) onSelect(at(e).i, e.shiftKey);
  };
  const key = (i: number) => (e: KeyboardEvent) => {
    const step = e.shiftKey || e.key.startsWith("Page") ? 1 : 0.1;
    const now = values[i] ?? 0;
    if (e.key === "ArrowUp" || e.key === "PageUp") onPaint(i, clamp(now + step));
    else if (e.key === "ArrowDown" || e.key === "PageDown") onPaint(i, clamp(now - step));
    else if (e.key === " " || e.key === "Enter") onSelect(i, e.shiftKey);
    else return;
    e.preventDefault();
  };

  return (
    <div className="overflow-x-auto no-scrollbar">
      <div style={{ minWidth: years.length * (many ? 26 : 40) }}>
        <div ref={box} className="relative cursor-ns-resize select-none" style={{ height: H }}
             onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { drag.current = null; }}>
          {[hi, lo].map((g) => (
            <span key={g} className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-hairline" style={{ top: y(g) }} />
          ))}
          <span className="pointer-events-none absolute left-0 right-0 border-t border-[var(--axis)]" style={{ top: zero }} />
          <div className="absolute inset-0 flex">
            {years.map((yr, i) => {
              const v = values[i];
              const on = selected.has(i);
              const top = v == null ? zero : Math.min(y(v), zero);
              const height = v == null ? 0 : Math.max(Math.abs(y(v) - zero), 2);
              return (
                <div key={yr.year} role="slider" tabIndex={0} aria-label={`Rendement ${yr.year}`}
                     aria-valuemin={-LIMIT} aria-valuemax={LIMIT} aria-valuenow={v ?? undefined}
                     aria-valuetext={v == null ? (yr.mixed ? "deux taux dans l'année" : "aucun") : shown(v)}
                     onKeyDown={key(i)}
                     title={`${yr.year}${yr.months < 12 ? ` (${yr.months} mois)` : ""} : ${v == null ? "—" : shown(v)}`}
                     className={cx("relative min-w-0 flex-1 rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent",
                       on ? "bg-accent/10" : "hover:bg-surface-2/70")}>
                  {v != null && (
                    <span className="absolute inset-x-[18%] rounded-[4px]"
                          style={{ top, height, background: v >= 0 ? "var(--good)" : "var(--critical)", opacity: on ? 1 : 0.72 }} />
                  )}
                  {v == null && yr.mixed && (
                    <span className="absolute inset-x-[18%] h-[2px] bg-ink-2" style={{ top: zero - 1 }} />
                  )}
                  {!many && v != null && (
                    <span className="num pointer-events-none absolute inset-x-0 text-center text-[10.5px] font-semibold text-ink-2"
                          style={{ top: v >= 0 ? top - 15 : top + height + 2 }}>{shown(v).replace(" %", "")}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div className="mt-1 flex">
          {years.map((yr, i) => (
            <span key={yr.year} className={cx("num min-w-0 flex-1 text-center text-[10.5px]", selected.has(i) ? "font-semibold text-ink" : "text-muted")}>
              {many ? `'${String(yr.year).slice(2)}` : yr.year}
            </span>
          ))}
        </div>
      </div>
      <div className="mt-0.5 flex justify-between text-[10.5px] text-muted num"><span>{shown(lo)}</span><span>échelle jusqu'à {shown(hi)}</span></div>
    </div>
  );
}

export function ByYear({ d, t, footer }: { d: Previsions; t: RateTarget; footer?: ReactNode }) {
  const { errors, busy, run } = useAction(d);
  // A pocket held at its value grows by 0 % a year: said so, not left blank.
  const held = t.pocket != null && t.own && t.segments.length === 0;
  const applied = t.years.map((y) => (held ? "0" : textOf(y.rate)));
  const [texts, setTexts] = useState<string[]>(applied);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);
  const [fill, setFill] = useState("");
  const values = texts.map(percentOf);
  const dirty = texts.join("|") !== applied.join("|");
  const blanks = values.filter((v) => v == null).length;
  const years = t.years;
  const last = years[years.length - 1];

  const paint = (i: number, p: number) => setTexts((xs) => xs.map((x, j) => (j === i ? textOf(p / 100) : x)));
  const select = (i: number, extend: boolean) => {
    if (extend && anchor != null) {
      const [a, b] = anchor < i ? [anchor, i] : [i, anchor];
      setSelected(new Set(Array.from({ length: b - a + 1 }, (_, k) => a + k)));
      return;
    }
    const next = new Set(selected);
    if (next.has(i)) next.delete(i); else next.add(i);
    setSelected(next);
    setAnchor(i);
  };
  const fillValue = percentOf(fill);
  const fillSelection = () => {
    if (fillValue == null) return;
    setTexts((xs) => xs.map((x, j) => (selected.has(j) ? textOf(clamp(fillValue) / 100) : x)));
  };
  const picked = [...selected].sort((a, b) => a - b);
  const range = picked.length === 0 ? "" : picked.length === 1 ? String(years[picked[0]].year)
    : picked.every((v, k) => k === 0 || v === picked[k - 1] + 1) ? `${years[picked[0]].year} – ${years[picked[picked.length - 1]].year}`
    : `${picked.length} années`;

  const apply = async () => {
    const before = t.segments;
    const wasOwn = t.own;
    const ok = await run({ action: "rate-years", rates: texts, ...targetOf(t) });
    if (!ok) return;
    setSelected(new Set());
    toast.success(t.pocket ? `Rendement année par année · ${t.label}` : "Rendement appliqué année par année", {
      action: { label: "Annuler", onClick: async () => {
        if (t.pocket && !wasOwn) await planAction(d.months, { action: "pocket-common", ...targetOf(t) });
        else await planAction(d.months, { action: "rate", months: before.length ? before.map(([m]) => String(m)) : [""],
                                          rates: before.length ? before.map(([, r]) => String(Math.round(r * 10000) / 100)) : [""], ...targetOf(t) });
        toast("Barème d'avant rétabli");
      } },
    });
  };

  return (
    <div>
      <Bars years={years} values={values} selected={selected} onPaint={paint} onSelect={select} />
      <div className="mt-3 flex min-h-9 flex-wrap items-center gap-2 rounded-xl bg-surface-2/50 px-3 py-1.5">
        {picked.length ? (
          <>
            <span className="text-[12.5px] font-medium">{range}</span>
            <div className="relative w-28">
              <Input value={fill} onChange={(e) => setFill(e.target.value)} inputMode="decimal" placeholder="4,5"
                     aria-label="Taux à donner aux années sélectionnées" className="w-full pr-8 text-right"
                     onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); fillSelection(); } }} />
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12.5px] text-muted">%</span>
            </div>
            <Button size="sm" type="button" disabled={fillValue == null} onClick={fillSelection}>Donner ce taux</Button>
            <Button size="sm" type="button" variant="ghost" onClick={() => setSelected(new Set())}>Désélectionner</Button>
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1 text-[12px] text-muted">
              Glisse une barre pour régler son année, ou clique des années pour les régler ensemble (Maj+clic : une plage). Au clavier : ↑ ↓ au dixième, Maj pour 1 %.
            </span>
            <Button size="sm" type="button" variant="ghost" onClick={() => { setSelected(new Set(years.map((_, i) => i))); setAnchor(0); }}>Tout sélectionner</Button>
          </>
        )}
      </div>
      <ol className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {years.map((yr, i) => {
          const error = errors[`rate-year-${i}`];
          return (
            <li key={yr.year} className={cx("rounded-xl border px-2.5 py-2 transition-colors",
              selected.has(i) ? "border-accent bg-accent/5" : "border-hairline")}>
              <button type="button" onClick={(e) => select(i, e.shiftKey)}
                      className="flex w-full items-baseline justify-between gap-1 text-left">
                <span className="num text-[13px] font-semibold">{yr.year}</span>
                <span className="text-[11px] text-muted">{yr.months < 12 ? `${yr.months} mois` : ""}</span>
              </button>
              <div className="relative mt-1">
                <Input value={texts[i]} inputMode="decimal" placeholder={yr.mixed ? "deux taux" : "—"}
                       onChange={(e) => setTexts(texts.map((x, j) => (j === i ? e.target.value : x)))}
                       aria-label={`Rendement ${yr.year}, en % par an`} invalid={!!error} className="w-full pr-8 text-right" />
                <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-[12px] text-muted">%</span>
              </div>
              {error && <p className="mt-1 text-[11.5px] leading-snug text-critical">{error}</p>}
            </li>
          );
        })}
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="primary" disabled={busy || !dirty || blanks > 0} onClick={() => void apply()}>Appliquer</Button>
        {dirty && <Button type="button" size="sm" variant="ghost" onClick={() => setTexts(applied)}>Revenir à l'appliqué</Button>}
        {dirty && <span className="text-[12px] text-warn">{blanks ? `${blanks} année${blanks > 1 ? "s" : ""} sans taux` : "modifié, pas encore appliqué"}</span>}
        {errors["rate-years"] && <span className="text-[12px] text-critical">{errors["rate-years"]}</span>}
      </div>
      <p className="mt-2 text-[12px] text-muted">
        Taux annuel, au centième près, composé chaque mois{last ? ` ; après ${last.year}, le taux de ${last.year} continue` : ""}. Les années de même taux se fondent en une période.
      </p>
      {footer}
    </div>
  );
}
