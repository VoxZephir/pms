/** The cash month by month: what comes in, what goes out and where, read
 * as bars before figures; the years fold, and past four years the decades. */
import { ArrowRight, ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState, type ReactNode } from "react";

import { Panel, cx } from "@/components/ui";
import { chf, plural, signedChf } from "@/lib/format";
import type { MonthRow, OneOff, Previsions } from "@/lib/previsions";

const COLORS = {
  income: "var(--good)",
  base: "var(--unsorted)",
  spent: "var(--warn)",
  moved: "var(--s1)",
};

/** What a month does with its money, in the four kinds the bar draws. */
function flows(r: MonthRow) {
  const spent = r.one_offs.filter((o) => !o.transfer).reduce((a, o) => a + o.amount, 0);
  const moved = r.one_offs.filter((o) => o.transfer).reduce((a, o) => a + o.amount, 0);
  return { income: r.income, base: r.spend - spent - moved, spent, moved, net: r.income - r.spend };
}

const POCKET = (o: OneOff) => (o.transfer === "3a" ? "3a" : "placement");

export function Months({ d }: { d: Previsions }) {
  const rows = d.projection.rows;
  const wealthByKey = new Map((d.wealth?.rows ?? []).map((r) => [r.key, r]));
  // One scale for the whole horizon: a big month looks big next to a quiet one.
  const scale = useMemo(() => Math.max(1, ...rows.map((r) => Math.max(r.income, r.spend))), [rows]);
  const groups = useMemo(() => {
    const years: { key: string; label: string; rows: MonthRow[] }[] = [];
    rows.forEach((r) => {
      const y = r.key.slice(0, 4);
      if (!years.length || years[years.length - 1].key !== y) years.push({ key: y, label: y, rows: [] });
      years[years.length - 1].rows.push(r);
    });
    if (years.length <= 4) return years.map((y) => ({ ...y, years: null as null | typeof years }));
    const decades: { key: string; label: string; rows: MonthRow[]; years: typeof years | null }[] = [];
    years.forEach((y) => {
      const decade = `${y.key.slice(0, 3)}0`;
      if (!decades.length || decades[decades.length - 1].key !== decade) {
        decades.push({ key: decade, label: `Années ${decade}`, rows: [], years: [] });
      }
      decades[decades.length - 1].rows.push(...y.rows);
      decades[decades.length - 1].years!.push(y);
    });
    return decades;
  }, [rows]);
  const lowKey = d.projection.low.key;
  const wealth = !!d.wealth;

  const monthList = (list: MonthRow[]) => (
    <div role="table" aria-label="Mois projetés">
      <div role="row" className={cx("hidden gap-4 border-b border-hairline px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted sm:grid",
        wealth ? "sm:grid-cols-[8.5rem_minmax(0,1fr)_5.5rem_6.5rem_6.5rem]" : "sm:grid-cols-[8.5rem_minmax(0,1fr)_5.5rem_6.5rem]")}>
        <span role="columnheader">Mois</span>
        <span role="columnheader">Sorties · entrées</span>
        <span role="columnheader" className="text-right">Net</span>
        <span role="columnheader" className="text-right">Cash fin</span>
        {wealth && <span role="columnheader" className="text-right">Patrimoine</span>}
      </div>
      {list.map((r) => <MonthLine key={r.key} r={r} scale={scale} low={r.key === lowKey} wealth={wealthByKey.get(r.key)?.total} showWealth={wealth} />)}
    </div>
  );

  return (
    <Panel title="Mois par mois" hint="chaque barre part du milieu : à gauche ce qui sort, à droite ce qui entre · le point bas est marqué">
      <Legend />
      <div className="space-y-2">
        {groups.map((g, i) => (
          <MonthFold key={g.key} label={g.label} rows={g.rows} defaultOpen={i === 0}>
            {g.years
              ? <div className="space-y-2 p-2">{g.years.map((y, j) => (
                  <MonthFold key={y.key} label={y.label} rows={y.rows} defaultOpen={i === 0 && j === 0}>{monthList(y.rows)}</MonthFold>
                ))}</div>
              : monthList(g.rows)}
          </MonthFold>
        ))}
      </div>
    </Panel>
  );
}

function Legend() {
  const items = [
    ["Revenus", COLORS.income], ["Dépense courante", COLORS.base],
    ["Ponctuels", COLORS.spent], ["Vers les placements", COLORS.moved],
  ] as const;
  return (
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
      {items.map(([label, color]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: color }} />{label}
        </span>
      ))}
    </div>
  );
}

/** Out to the left of the middle, in to the right: base, one-offs and
 * transfers stacked from the axis outwards. */
function FlowBar({ f, scale }: { f: ReturnType<typeof flows>; scale: number }) {
  const pct = (v: number) => `${(Math.max(v, 0) / scale) * 50}%`;
  const parts = [
    { key: "base", value: f.base, title: `Dépense courante −${chf(f.base, 0)}` },
    { key: "spent", value: f.spent, title: `Ponctuels −${chf(f.spent, 0)}` },
    { key: "moved", value: f.moved, title: `Vers les placements −${chf(f.moved, 0)}` },
  ] as const;
  return (
    <div className="relative h-3.5 w-full" aria-hidden>
      <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--axis)" }} />
      <div className="absolute inset-y-0 left-0 right-1/2 flex flex-row-reverse">
        {parts.map((p) => p.value > 0.5 && (
          <span key={p.key} title={p.title} className="h-full first:rounded-r-none last:rounded-l-[4px]"
                style={{ width: `${(p.value / scale) * 100}%`, background: COLORS[p.key], opacity: p.key === "base" ? 0.55 : 0.9 }} />
        ))}
      </div>
      {f.income > 0.5 && (
        <span title={`Revenus +${chf(f.income, 0)}`} className="absolute inset-y-0 left-1/2 rounded-r-[4px]"
              style={{ width: pct(f.income), background: COLORS.income, opacity: 0.8 }} />
      )}
    </div>
  );
}

function MonthLine({ r, scale, low, wealth, showWealth }: {
  r: MonthRow; scale: number; low: boolean; wealth?: number; showWealth: boolean;
}) {
  const f = flows(r);
  const events = r.one_offs.filter((o) => !o.transfer || o.source !== "contribution");
  const series = r.one_offs.filter((o) => o.transfer && o.source === "contribution");
  // A series is said once per pocket, short: it comes back every month.
  const perPocket = new Map<string, number>();
  series.forEach((o) => perPocket.set(POCKET(o), (perPocket.get(POCKET(o)) ?? 0) + o.amount));
  return (
    <div role="row" className={cx("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 border-b border-hairline px-3 py-2.5 text-[13px] last:border-b-0",
      showWealth ? "sm:grid-cols-[8.5rem_minmax(0,1fr)_5.5rem_6.5rem_6.5rem]" : "sm:grid-cols-[8.5rem_minmax(0,1fr)_5.5rem_6.5rem]",
      low && "bg-[color-mix(in_srgb,var(--s0)_8%,transparent)]")}>
      <div role="cell" className="min-w-0">
        <span className="font-medium capitalize">{r.label}</span>
        {r.partial && <span className="ml-1.5 whitespace-nowrap rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted" title="ne compte que ce qu'il reste à venir">reste du mois</span>}
        {low && <span className="ml-1.5 whitespace-nowrap rounded-md bg-[color-mix(in_srgb,var(--s0)_18%,transparent)] px-1.5 py-0.5 text-[11px] font-semibold text-s0">point bas</span>}
      </div>
      <div role="cell" className="order-5 col-span-2 min-w-0 sm:order-none sm:col-span-1">
        <FlowBar f={f} scale={scale} />
        {(events.length > 0 || perPocket.size > 0) && (
          <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-ink-2">
            {events.map((o, i) => (
              <li key={i} className="inline-flex min-w-0 items-center gap-1.5"
                  title={o.source === "suggestion" ? "suggéré par l'historique, pas encore déclaré" : o.transfer ? "virement : sort du cash, reste dans le patrimoine" : undefined}>
                <i className={cx("inline-block size-2 shrink-0 rounded-full", o.source === "suggestion" && "border border-dashed bg-transparent")}
                   style={o.source === "suggestion" ? { borderColor: COLORS.spent } : { background: o.transfer ? COLORS.moved : COLORS.spent }} />
                {o.date && <span className="num text-muted">{o.date.slice(8, 10)}.{o.date.slice(5, 7)}</span>}
                <span className={cx("truncate", o.source === "suggestion" && "italic")}>{o.label}</span>
                <span className="num font-medium text-ink">−{chf(o.amount, 0)}</span>
              </li>
            ))}
            {[...perPocket].map(([pocket, amount]) => (
              <li key={pocket} className="inline-flex items-center gap-1 text-muted" title="versement programmé : sort du cash, reste dans le patrimoine">
                <ArrowRight size={12} style={{ color: COLORS.moved }} />{pocket} <span className="num">{chf(amount, 0)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div role="cell" className={cx("num order-3 text-[12.5px] sm:order-none sm:text-right", f.net >= 0 ? "text-good" : "text-critical")}>
        <span className="text-muted sm:hidden">net </span>{signedChf(f.net, 0)}
      </div>
      <div role="cell" className={cx("num text-right text-[14px] font-semibold", r.end < 0 && "text-critical")}>{chf(r.end, 0)}</div>
      {showWealth && (
        <div role="cell" className="num order-4 text-right text-[12.5px] text-muted sm:order-none" title="patrimoine en fin de mois">
          <span className="sm:hidden">patrimoine </span>{wealth != null ? chf(wealth, 0) : "—"}
        </div>
      )}
    </div>
  );
}

/** The cash ends of a fold, as a line: the year's shape before its rows. */
function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 60},${16 - ((v - lo) / (hi - lo || 1)) * 14 - 1}`).join(" ");
  return (
    <svg width="60" height="16" className="shrink-0" aria-hidden>
      <polyline points={pts} fill="none" stroke="var(--s0)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** One year, or one decade: where the cash goes over it, and how many of
 * each kind of movement it holds -- a scheduled series is not a "ponctuel". */
function MonthFold({ label, rows, defaultOpen, children }: {
  label: string; rows: MonthRow[]; defaultOpen: boolean; children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const kinds = { declared: 0, contribution: 0, suggestion: 0 } as Record<string, number>;
  rows.forEach((r) => r.one_offs.forEach((o) => { kinds[o.source] = (kinds[o.source] ?? 0) + 1; }));
  const said = [
    kinds.declared && plural(kinds.declared, "ponctuel"),
    kinds.contribution && plural(kinds.contribution, "versement programmé", "versements programmés"),
    kinds.suggestion && plural(kinds.suggestion, "suggestion"),
  ].filter(Boolean).join(" · ");
  const start = rows[0].start, end = rows[rows.length - 1].end;
  return (
    <div className="overflow-hidden rounded-2xl border border-hairline">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
              className="flex w-full flex-wrap items-center gap-x-2.5 gap-y-0.5 bg-surface-2/50 px-3 py-2.5 text-left text-[13.5px]">
        <ChevronRight size={15} className={cx("text-muted transition-transform", open && "rotate-90")} />
        <b>{label}</b>
        <Spark values={[start, ...rows.map((r) => r.end)]} />
        <span className="num text-ink-2">{chf(start, 0)} → {chf(end, 0)}</span>
        <span className={cx("num text-[12.5px] font-medium", end >= start ? "text-good" : "text-critical")}>{signedChf(end - start, 0)}</span>
        {said && <span className="w-full pl-6 text-[12px] text-muted sm:w-auto sm:pl-0">· {said}</span>}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
