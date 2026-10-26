/** The ordinary month, one bar per calendar month: the median of the observed
 * months, the seasonal spike (the annual bill the history detected) drawn
 * light on top of what remains, and the baseline as a dashed rule. Shared by
 * the analysis and the forecast -- one chart, no second copy. */
import { Columns } from "@/charts/Columns";
import { chf } from "@/lib/format";

import { Table } from "./Table";
import { Chip, Reveal } from "./ui";

export interface ProfileMonth {
  month: number; label: string; short: string;
  raw_median: number; stripped_median: number; seasonal_median: number; iqr: number;
  years: number[];
  seasonal: { category: string; amount: number; years?: number[] }[];
}

export function MonthlyProfile({ profile, baseline }: { profile: ProfileMonth[]; baseline: number }) {
  const cols = profile.map((m) => ({
    key: String(m.month), label: m.label, short: m.short,
    segments: [
      { name: "Hors saisonnier", value: m.stripped_median, color: "var(--s0)" },
      { name: "Pic saisonnier", value: m.seasonal_median, color: "color-mix(in srgb, var(--s0) 35%, var(--surface))" },
    ],
    total: m.stripped_median + m.seasonal_median,
  }));
  return (
    <>
      <Columns columns={cols} height={250} stackOrder="given" reference={baseline}
               referenceLabel={`base ${chf(baseline, 0)}`}
               tipFooter={(c) => {
                 const m = profile.find((x) => String(x.month) === c.key)!;
                 return (
                   <div className="space-y-0.5">
                     <div className="flex justify-between gap-3"><span>Médiane brute</span><b className="num">{chf(m.raw_median, 0)}</b></div>
                     <div className="text-muted">{m.years.join(", ")}</div>
                   </div>
                 );
               }}
               ariaLabel="Dépense médiane par mois calendaire" />
      <Reveal className="mt-3" summary="Voir le détail en table">
        <Table rows={profile} rowKey={(r) => String(r.month)} dense
               cols={[
                 { key: "label", label: "Mois", render: (r) => r.label },
                 { key: "raw", label: "Médiane brute", numeric: true, sort: (r) => r.raw_median, render: (r) => chf(r.raw_median, 0) },
                 { key: "seasonal", label: "Pics retirés", wide: true, render: (r) => r.seasonal.length
                   ? <span className="flex flex-wrap gap-1">{r.seasonal.map((s) => <Chip key={s.category}>~{chf(s.amount, 0)} · {s.category}</Chip>)}</span>
                   : <span className="text-muted">—</span> },
                 { key: "stripped", label: "Hors saisonnier", numeric: true, sort: (r) => r.stripped_median, render: (r) => chf(r.stripped_median, 0) },
                 { key: "iqr", label: "Dispersion", numeric: true, title: "écart entre les quartiles des mois bruts", sort: (r) => r.iqr, render: (r) => chf(r.iqr, 0) },
                 { key: "years", label: "Années", numeric: true, wide: true, render: (r) => r.years.join(" · ") },
               ]} />
      </Reveal>
    </>
  );
}
