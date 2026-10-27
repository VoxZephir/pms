/** Forecast against what happened: the plan's forecasts kept month by
 * month, or the history-only method replayed from past month-ends. Each
 * finished month says what was expected of it, what came, and where the
 * gap came from; a steady bias offers the spend that would correct it. */
import { useState } from "react";
import { toast } from "sonner";

import { Lines, spreadTicks, type LineSeries } from "@/charts/Lines";
import { Button, Callout, Note, Panel, Segmented, Skeleton, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { MONTHS_SHORT, chf, frDate, signedChf } from "@/lib/format";
import { planAction, type Previsions } from "@/lib/previsions";

interface Point { key: string; label: string; ahead: number; forecast: number; actual: number; gap: number; income_gap: number; outflow_gap: number }
interface Month extends Point {
  made: string; plan: string | null; forecast_income: number; forecast_outflow: number; income: number; outflow: number;
  why: { category: string; over: number }[];
}
interface Side { mean: number; steady: boolean }
interface Source {
  runs: { made: string; plan: string | null; start: number; points: Point[] }[];
  months: Month[];
  bias: { count: number; income: Side; outflow: Side; cash: Side } | null;
  suggest_spend: number | null;
  kept?: number; first?: string | null;
}
interface Hindsight { empty?: boolean; plan: Source; method: Source; spend: number; spend_declared: boolean }

type Which = "plan" | "method";

const short = (key: string) => `${MONTHS_SHORT[Number(key.slice(5, 7)) - 1]} ${key.slice(2, 4)}`;

export function Hindsight({ d }: { d: Previsions }) {
  const { data } = useApi<Hindsight>("/api/previsions/hindsight");
  const [chosen, setChosen] = useState<Which | null>(null);
  if (!data || data.empty) return data?.empty ? null : <Panel title="Prévu contre réel"><Skeleton className="h-48" /></Panel>;
  const which: Which = chosen ?? (data.plan.months.length ? "plan" : "method");
  const s = data[which];
  return (
    <Panel id="p-hindsight" title="Prévu contre réel"
           hint="chaque mois fini, ce que la prévision en attendait un mois avant, et d'où vient l'écart"
           actions={<Segmented<Which> label="Quelle prévision" size="sm" value={which} onChange={setChosen}
                                     options={[{ id: "plan", label: "Ton plan" }, { id: "method", label: "La méthode seule" }]} />}>
      {which === "plan" && !s.months.length ? (
        <Callout title={s.kept ? "Première comparaison le mois prochain" : "La prévision de ce mois est gardée dès maintenant"}>
          {s.first ? <>Ta prévision est gardée depuis le {frDate(s.first)}, une par mois. </> : null}
          Un mois se compare quand il est entier dans le relevé. En attendant, « La méthode seule » rejoue la prévision depuis l'historique, sans plan.
        </Callout>
      ) : !s.months.length ? (
        <Callout>Il faut au moins sept mois de relevé pour rejouer une prévision.</Callout>
      ) : (
        <>
          <Verdict d={d} data={data} which={which} />
          <Chart s={s} />
          <Table s={s} />
        </>
      )}
      <Note>
        {which === "plan"
          ? "La prévision gardée est celle du plan affiché la première fois que la page s'ouvre dans le mois. Écart = réel − prévu : revenu en plus ou sorties en moins font un écart positif."
          : "La méthode seule : depuis chaque fin de mois passée, le relevé coupé là et la prévision refaite sans plan (revenu et dépense médians, factures saisonnières). Elle dit si la méthode a tendance à se tromper, et dans quel sens."}
      </Note>
    </Panel>
  );
}

function Verdict({ d, data, which }: { d: Previsions; data: Hindsight; which: Which }) {
  const s = data[which];
  const b = s.bias;
  if (!b) return null;
  const side = (x: Side, more: string, less: string) =>
    Math.abs(x.mean) < 20 ? "justes à quelques francs près"
      : `${x.mean > 0 ? more : less} de ${chf(Math.abs(x.mean), 0)} CHF par mois en moyenne`;
  const apply = async () => {
    const before = data.spend_declared ? chf(data.spend, 0) : "";
    const r = await planAction(d.months, { action: "spend", amount: String(s.suggest_spend) });
    if (r.errors) { toast.error(Object.values(r.errors)[0]); return; }
    toast.success(`Dépense de base : ${chf(s.suggest_spend!, 0)} CHF`, {
      action: { label: "Annuler", onClick: () => void planAction(d.months, { action: "spend", amount: before.replace(/['’]/g, "") }) },
    });
  };
  return (
    <div className="mb-4 space-y-1.5 text-[13.5px] leading-relaxed text-ink-2">
      <p>
        Sur les {b.count} derniers mois, un mois avant : tes <b className="text-ink">sorties</b> ont été {side(b.outflow, "plus hautes que prévu", "plus basses que prévu")}
        {b.outflow.steady ? " — une habitude, pas du bruit" : Math.abs(b.outflow.mean) >= 20 ? ", mais d'un mois à l'autre l'écart change de sens" : ""}.
        {" "}Ton <b className="text-ink">revenu</b> a été {side(b.income, "plus haut que prévu", "plus bas que prévu")}.
      </p>
      {s.suggest_spend != null && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-3 py-2">
          <span className="min-w-0 flex-1">Une dépense de base de <b className="num text-ink">{chf(s.suggest_spend, 0)} CHF</b> au lieu de {chf(data.spend, 0)} aurait rattrapé cet écart.</span>
          <Button size="sm" onClick={() => void apply()}>Déclarer {chf(s.suggest_spend, 0)} CHF</Button>
        </div>
      )}
    </div>
  );
}

function Chart({ s }: { s: Source }) {
  // One axis of months: those forecast from, and those forecast.
  const keys = [...new Set([
    ...s.runs.map((r) => r.made.slice(0, 7)),
    ...s.runs.flatMap((r) => r.points.map((p) => p.key)),
  ])].sort();
  const at = new Map(keys.map((k, i) => [k, i]));
  const actual: (number | null)[] = keys.map(() => null);
  s.runs.forEach((r) => {
    actual[at.get(r.made.slice(0, 7))!] ??= r.start;
    r.points.forEach((p) => { actual[at.get(p.key)!] = p.actual; });
  });
  const series: LineSeries[] = s.runs.map((r, i) => {
    const values: (number | null)[] = keys.map(() => null);
    values[at.get(r.made.slice(0, 7))!] = r.start;
    r.points.forEach((p) => { values[at.get(p.key)!] = p.forecast; });
    return { key: `f${i}`, name: `Prévu le ${frDate(r.made)}`, color: "var(--s1)", values, dash: true, width: 1.25, faint: true, silent: true };
  });
  series.push({ key: "actual", name: "Réel", color: "var(--s0)", values: actual, width: 2.5 });
  const byKey = new Map(s.months.map((m) => [m.key, m]));
  return (
    <div className="mb-4">
      <Lines xs={keys.map((_, i) => i)} height={220} zero={false} series={series}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             tipExtra={(i) => {
               const m = byKey.get(keys[i]);
               return m ? [{ name: "Prévu un mois avant", value: `${chf(m.forecast, 0)}` }, { name: "Écart", value: signedChf(m.gap) }] : [];
             }}
             xLabel={(i) => short(keys[i])}
             xTicks={(w) => spreadTicks(keys.length, w, (i) => short(keys[i]), 64)}
             ariaLabel="Cash réel en fin de mois, et ce que chaque prévision en attendait" />
      <p className="mt-1.5 flex flex-wrap gap-x-4 text-[12px] text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-s0" />cash réel en fin de mois</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-0 w-4 border-t-2 border-dashed border-s1" />chaque prévision, sur ses trois mois</span>
      </p>
    </div>
  );
}

function Table({ s }: { s: Source }) {
  const months = [...s.months].reverse();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-[13px]">
        <thead>
          <tr className="text-left text-[12px] text-muted">
            <th className="py-1.5 font-medium">Mois</th>
            <th className="py-1.5 text-right font-medium">Prévu</th>
            <th className="py-1.5 text-right font-medium">Réel</th>
            <th className="py-1.5 text-right font-medium">Écart</th>
            <th className="py-1.5 pl-4 font-medium">D'où vient l'écart</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline">
          {months.map((m) => (
            <tr key={m.key} data-hindsight-month={m.key}>
              <td className="py-2 capitalize">{m.label}</td>
              <td className="num py-2 text-right text-ink-2">{chf(m.forecast, 0)}</td>
              <td className="num py-2 text-right">{chf(m.actual, 0)}</td>
              <td className={cx("num py-2 text-right font-medium", Math.abs(m.gap) < 50 ? "text-muted" : m.gap > 0 ? "text-good" : "text-critical")}>{signedChf(m.gap)}</td>
              <td className="py-2 pl-4 text-[12.5px] text-ink-2">{why(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The gap in words: income and outflows split it exactly; an overrun is
 * traced to the categories above their usual month. */
function why(m: Month): string {
  const parts: string[] = [];
  if (Math.abs(m.income_gap) >= 50) parts.push(`revenu ${signedChf(m.income_gap)}`);
  if (m.outflow_gap >= 50) {
    const cats = m.why.slice(0, 2).map((w) => `${w.category[0].toLowerCase()}${w.category.slice(1)} +${chf(w.over, 0)}`);
    parts.push(`sorties +${chf(m.outflow_gap, 0)}${cats.length ? ` (surtout ${cats.join(", ")})` : ""}`);
  } else if (m.outflow_gap <= -50) {
    parts.push(`sorties ${signedChf(m.outflow_gap)}`);
  }
  return parts.join(" · ") || "comme prévu";
}
