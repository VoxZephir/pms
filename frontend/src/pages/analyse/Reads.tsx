/** The past spending, read several ways: the four figures, what changed in
 * a year, each category with its line, the rhythm of a month, the days of
 * the week, and one category up close. The figures are the server's
 * (`lookback.py`); this file lays them out and draws them. */
import { ArrowLeft } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { Columns } from "@/charts/Columns";
import { Lines, spreadTicks } from "@/charts/Lines";
import { Diverging } from "@/components/Diverging";
import { Table } from "@/components/Table";
import { ButtonLink, Card, Chip, Dot, Note, Panel, cx } from "@/components/ui";
import { MONTHS, MONTHS_SHORT, chf, frDate, signedChf } from "@/lib/format";
import { useView } from "@/lib/url";
import type { Analyse, CategoryRow, Drill, Kind } from "./types";

export const KEEP = ["year", "cat"] as const;
const keep = { keep: KEEP };

const slotColor = (slot: number | null | undefined) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");

function useSlots(a: Analyse) {
  return useMemo(() => new Map(a.categories.map((c) => [c.category, c.slot])), [a.categories]);
}

/* -------------------------------------------------------------- headline */

export function Headline({ a }: { a: Analyse }) {
  const h = a.headline;
  const y = h.year;
  const tiles = [
    { label: "Un mois de dépense", value: h.spending != null ? chf(h.spending, 0) : "—", unit: "CHF",
      sub: `médiane de ${h.months} mois entiers` },
    { label: "Un mois de revenus", value: h.income != null ? chf(h.income, 0) : "—", unit: "CHF", sub: "médiane, mêmes mois" },
    { label: "Part gardée", value: h.saving_rate != null ? `${Math.round(h.saving_rate * 100)}` : "—", unit: "%",
      sub: "du revenu, un mois ordinaire (médiane)", tone: h.saving_rate != null ? (h.saving_rate >= 0 ? "text-good" : "text-critical") : "" },
    y ? { label: `${h.year_months} derniers mois`, value: chf(y.now, 0), unit: "CHF",
      sub: <>dépensés · <b className={cx(y.delta > 0 ? "text-critical" : "text-good")}>{signedChf(y.delta, 0)}</b>
        {y.pct != null && ` (${y.pct > 0 ? "+" : ""}${y.pct.toFixed(1)}\u00a0%)`} contre les {h.year_months} d'avant</> }
      : null,
  ].filter((t): t is NonNullable<typeof t> => t != null);
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" aria-label="L'essentiel">
      {tiles.map((t) => (
        <Card key={t.label} className="p-4">
          <div className="eyebrow truncate">{t.label}</div>
          <div className={cx("mt-1.5 flex items-baseline gap-1 text-[24px] font-semibold leading-none tracking-[-0.025em]", "tone" in t && t.tone)}>
            <span className="num">{t.value}</span><span className="text-[12px] font-medium tracking-normal text-muted">{t.unit}</span>
          </div>
          <div className="mt-1.5 text-[12px] leading-snug text-muted">{t.sub}</div>
        </Card>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- changes */

/** Each category, the last months against as many before: a bar to the
 * right is a rise, to the left a fall, all on one scale. */
export function Changes({ a }: { a: Analyse }) {
  const { href } = useView();
  const slots = useSlots(a);
  const [all, setAll] = useState(false);
  const ch = a.change;
  if (!ch || !ch.rows.length) return null;
  const rows = all ? ch.rows : ch.rows.slice(0, 8);
  return (
    <Panel id="p-changes" title="Ce qui a changé"
           hint={`${ch.last.label} contre ${ch.before.label} · ${ch.months} mois entiers de chaque côté`}>
      <Diverging ariaLabel="Variation de chaque catégorie"
                 rows={rows.map((r) => ({ key: r.category, label: r.category, before: r.before, now: r.now, delta: r.delta,
                                          color: slotColor(slots.get(r.category)), to: href({ cat: r.category }, keep) }))} />
      {ch.rows.length > 8 && (
        <button type="button" onClick={() => setAll(!all)} className="mt-2 text-[12.5px] font-medium text-accent hover:underline">
          {all ? "Moins" : `Les ${ch.rows.length} catégories`}
        </button>
      )}
      <Note>
        En tout {chf(ch.total.before, 0)} → {chf(ch.total.now, 0)} CHF, <b className={ch.total.delta > 0 ? "text-critical" : "text-good"}>{signedChf(ch.total.delta, 0)}</b>.
        {" "}À droite, une catégorie qui a coûté plus ; à gauche, moins. Une catégorie ouvre son détail.
      </Note>
    </Panel>
  );
}

/* ------------------------------------------------------------ categories */

const KINDS: Record<Kind, { label: string; title: string; tone: "neutral" | "accent" | "warn" }> = {
  regular: { label: "régulière", title: "presque chaque mois, d'un montant proche", tone: "neutral" },
  variable: { label: "variable", title: "la plupart des mois, d'un montant qui change", tone: "neutral" },
  occasional: { label: "ponctuelle", title: "certains mois seulement", tone: "warn" },
  seasonal: { label: "saisonnière", title: "une facture au même mois, deux ans de suite", tone: "accent" },
};

/** A category's months as small bars: its shape, at its own scale. */
function SparkBars({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values, 0);
  if (!values.length || max <= 0) return null;
  const w = 100 / values.length;
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-6 w-24 sm:w-32" aria-hidden>
      {values.map((v, i) => {
        const h = (v / max) * 22;
        return v > 0
          ? <rect key={i} x={i * w + w * 0.15} width={w * 0.7} y={24 - h} height={Math.max(h, 0.8)} fill={color} rx={0.6} />
          : <rect key={i} x={i * w + w * 0.15} width={w * 0.7} y={23} height={1} fill="var(--hairline-2)" />;
      })}
    </svg>
  );
}

export function Categories({ a }: { a: Analyse }) {
  const { href } = useView();
  return (
    <Panel id="p-categories" title="Par catégorie"
           hint={`la médiane d'un mois, les ${Math.min(24, a.whole_months)} derniers mois en barres, la part de l'année, la régularité`}>
      <Table<CategoryRow> rows={a.categories} rowKey={(r) => r.category}
             rowClass={(r) => (r.category === a.drill?.category ? "bg-surface-2/70" : undefined)}
             cols={[
               { key: "category", label: "Catégorie", sort: (r) => r.category, render: (r) => (
                 <Link to={href({ cat: r.category === a.drill?.category ? null : r.category }, keep)} preventScrollReset
                       className="inline-flex items-center gap-2 font-medium underline-offset-2 hover:underline">
                   <Dot color={slotColor(r.slot)} />{r.category}</Link>) },
               { key: "spark", label: "Mois", render: (r) => <SparkBars values={r.spark} color={slotColor(r.slot)} /> },
               { key: "median", label: "Médiane / mois", numeric: true, sort: (r) => r.median, render: (r) => chf(r.median, 0) },
               { key: "share", label: "Part", numeric: true, sort: (r) => r.share, title: "part de la dépense des 12 derniers mois entiers",
                 render: (r) => `${r.share.toFixed(r.share < 10 ? 1 : 0)} %` },
               { key: "kind", label: "Régularité", sort: (r) => r.months_with, render: (r) => (
                 <span title={`${KINDS[r.kind].title} · ${r.months_with} mois sur ${r.months}`}>
                   <Chip tone={KINDS[r.kind].tone}>{KINDS[r.kind].label}</Chip></span>), wide: true },
               { key: "trend", label: "Tendance", numeric: true, sort: (r) => r.trend ?? 0,
                 title: "médiane de la 2ᵉ moitié des mois observés contre la 1ʳᵉ",
                 render: (r) => (r.trend == null ? <span className="text-muted">—</span>
                   : <span className={cx(r.trend >= 3 ? "text-critical" : r.trend <= -3 ? "text-good" : "")}>{r.trend > 0 ? "+" : ""}{r.trend.toFixed(1)} %</span>) },
               { key: "seasonal", label: "Saison", render: (r) => (r.seasonal
                 ? <Link to="/previsions" title={`Facturé ${r.seasonal.years.join(", ")} — la confirmer dans les prévisions`}>
                     <Chip tone="accent">chaque {r.seasonal.month_label} · ~{chf(r.seasonal.amount, 0)}</Chip></Link>
                 : <span className="text-muted">{r.peak_month_label}</span>) },
             ]} />
      <Note>
        Régulière : presque chaque mois, d'un montant proche (le loyer). Variable : la plupart des mois. Ponctuelle : certains mois.
        Saisonnière : la même facture au même mois deux ans de suite — sa médiane mélange la facture et les petits mois, la prochaine se déclare dans les prévisions.
        Sans saison, la dernière colonne dit le mois où la catégorie coûte le plus. La tendance compare la seconde moitié des mois observés à la première.
      </Note>
    </Panel>
  );
}

/* ---------------------------------------------------------------- rhythm */

/** How a month spends itself: the money gone by each day, the ordinary
 * month with its middle half, and the latest month against it. */
export function Rhythm({ a }: { a: Analyse }) {
  const r = a.rhythm;
  if (!r) return null;
  const xs = r.median.map((_, i) => i + 1);
  const cur = r.current;
  const series = [
    { key: "median", name: "Mois ordinaire (médiane)", color: "var(--ink-2)", values: r.median, width: 2, dash: true },
    ...(cur ? [{ key: "current", name: cur.label, color: "var(--s0)", width: 2.5,
                 values: r.median.map((_, i) => (i < cur.values.length ? cur.values[i] : null)) }] : []),
  ];
  return (
    <Panel id="p-rhythm" title="Le rythme du mois" hint={`ce qui est parti au fil des jours · ${r.span.label}`}>
      <Lines xs={xs} series={series} height={220}
             band={{ low: r.low, high: r.high, color: "var(--ink-2)" }}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             xLabel={(i) => `le ${i + 1}`}
             xTicks={(w) => spreadTicks(31, w, (i) => String(i + 1), 40)}
             ariaLabel="Dépense cumulée au fil du mois" />
      <div className="mt-2 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><i className="h-0 w-3 border-t-2 border-dashed border-ink-2" />mois ordinaire</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-3 rounded-sm bg-ink-2/20" />la moitié des mois</span>
        {cur && <span className="inline-flex items-center gap-1.5"><Dot color="var(--s0)" />{cur.label}</span>}
      </div>
      <Note>
        {r.half_day != null && <>Un mois ordinaire a dépensé sa moitié le {r.half_day}. </>}
        {cur && <>En {cur.label}{cur.whole ? "" : `, au ${cur.day}`} : {chf(cur.values[cur.values.length - 1], 0)} CHF, {" "}
          <b className={cur.vs_median > 0 ? "text-critical" : "text-good"}>{signedChf(cur.vs_median, 0)}</b> par rapport au mois ordinaire au même jour. </>}
        Médiane des {r.months} derniers mois entiers ; la bande va du quart le plus sobre au quart le plus dépensier.
      </Note>
    </Panel>
  );
}

/* -------------------------------------------------------------- weekdays */

export function WeekdayBars({ a }: { a: Analyse }) {
  const w = a.weekdays;
  if (!w) return null;
  const max = Math.max(...w.rows.map((r) => r.per_day));
  return (
    <Panel id="p-weekdays" title="Les jours de la semaine" hint="paiements par carte, en moyenne par jour, 12 derniers mois entiers">
      <Columns height={200} fixedMax={max * 1.1}
               columns={w.rows.map((r, i) => ({
                 key: r.day, label: r.day.slice(0, 3) + ".", total: r.per_day,
                 segments: [{ name: r.day, value: r.per_day, color: i >= 5 ? "var(--s4)" : "var(--s0)" }],
               }))}
               format={(v) => chf(v, 0)}
               tipRows={(c) => {
                 const r = w.rows.find((x) => x.day === c.key)!;
                 return [{ name: "par jour", value: `${chf(r.per_day, 0)} CHF` }, { name: "paiements", value: String(r.count) }];
               }}
               ariaLabel="Dépense par carte selon le jour de la semaine" />
      <Note>
        Un jour de semaine coûte {chf(w.week, 0)} CHF en moyenne, un jour de week-end {chf(w.weekend, 0)} CHF
        {w.week > 0 && ` (${w.weekend >= w.week ? "+" : "−"}${Math.abs(Math.round((w.weekend / w.week - 1) * 100))} %)`}.
        Les cartes seulement : un loyer ou un impôt tombe le jour où la banque le passe.
      </Note>
    </Panel>
  );
}

/* ---------------------------------------------------------------- detail */

/** One category up close: its figures, its months, each year against the
 * others, and who the money went to. */
export function CategoryDetail({ a, d }: { a: Analyse; d: Drill }) {
  const { href } = useView();
  const color = slotColor(a.categories.find((c) => c.category === d.category)?.slot);
  const yearColors = ["var(--s5)", "var(--s3)", "var(--s2)", "var(--s0)"];
  const years = d.years.slice(-4);
  const xs = MONTHS.map((_, i) => i);
  const top = Math.max(...d.merchants.map((m) => m.amount), 1);
  const tiles = [
    ["Médiane / mois", `${chf(d.median, 0)} CHF`, "les mois où elle a coûté"],
    ["Moyenne / mois", `${chf(d.mean, 0)} CHF`, `sur ${d.months} mois entiers`],
    ["Le plus cher", `${chf(d.max, 0)} CHF`, d.max_month ?? "—"],
    ["12 derniers mois", `${chf(d.total_year, 0)} CHF`, `${d.count_year} paiements`],
  ];
  return (
    <Panel id="p-detail" title={<span className="inline-flex items-center gap-2"><Dot color={color} />{d.category}</span>}
           hint="la catégorie de près : ses mois, chaque année, à qui l'argent est allé"
           actions={<ButtonLink size="sm" to={href({ cat: null }, keep)} preventScrollReset><ArrowLeft size={14} />Toutes les catégories</ButtonLink>}>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map(([label, value, sub]) => (
          <div key={label} className="rounded-2xl bg-surface-2/60 p-3">
            <div className="eyebrow">{label}</div>
            <div className="num mt-1 text-[18px] font-semibold">{value}</div>
            <div className="text-[12px] text-muted">{sub}</div>
          </div>
        ))}
      </div>
      <Columns height={220} reference={d.median} referenceLabel={`médiane ${chf(d.median, 0)}`}
               columns={d.rows.map((r) => ({ key: r.key, label: r.label, segments: [{ name: d.category, value: r.amount, color }], total: r.amount }))}
               ariaLabel={`Dépense mensuelle de ${d.category}`} />
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        {years.length > 1 && (
          <div>
            <h3 className="mb-2 text-[14px] font-semibold">Année contre année</h3>
            <Lines xs={xs} height={190}
                   series={years.map((y, i) => ({ key: String(y.year), name: String(y.year), color: yearColors[(i + 4 - years.length) % 4],
                                                  values: y.months, width: i === years.length - 1 ? 2.5 : 1.75 }))}
                   tipFormat={(v) => `${chf(v, 0)} CHF`}
                   xLabel={(i) => MONTHS[i]}
                   xTicks={(w) => spreadTicks(12, w, (i) => MONTHS_SHORT[i], 44)}
                   ariaLabel={`${d.category}, chaque année mois par mois`} />
            <div className="mt-2 flex flex-wrap gap-3 text-[12.5px] text-ink-2">
              {years.map((y, i) => <span key={y.year} className="inline-flex items-center gap-1.5"><Dot color={yearColors[(i + 4 - years.length) % 4]} />{y.year}</span>)}
            </div>
          </div>
        )}
        {d.merchants.length > 0 && (
          <div>
            <h3 className="mb-2 text-[14px] font-semibold">À qui, sur 12 mois</h3>
            <ul className="space-y-2">
              {d.merchants.map((m) => (
                <li key={m.name} className="text-[13px]">
                  <div className="flex items-baseline justify-between gap-3">
                    <Link to={`/transactions?preset=12m&q=${encodeURIComponent(m.name)}`} className="min-w-0 truncate underline-offset-2 hover:underline">{m.name}</Link>
                    <b className="num shrink-0">{chf(m.amount, 0)}</b>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full rounded-full" style={{ width: `${(m.amount / top) * 100}%`, background: color }} />
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">{m.count} fois · {chf(m.median, 0)} d'habitude · {m.share.toFixed(0)} % de la catégorie · dernier le {frDate(m.last)}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}


