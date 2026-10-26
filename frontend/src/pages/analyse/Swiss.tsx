/** The ledger against Switzerland: one's own price rise against the
 * consumer price index, one's month against the average Swiss household.
 * Figures from `swiss.py`; the public ones carry their source. */
import { ExternalLink } from "lucide-react";

import { Lines, spreadTicks } from "@/charts/Lines";
import { Note, Panel, cx } from "@/components/ui";
import { MONTHS_SHORT, chf, frDate, monthLabel, signedChf } from "@/lib/format";
import type { Households, Inflation } from "./types";

const signedPct = (v: number, digits = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits).replace(".", ",")} %`;

export function MyInflation({ inf }: { inf: Inflation }) {
  const cpi = inf.cpi;
  const xs = cpi.monthly.map((_, i) => i);
  const top = Math.max(...inf.rows.map((r) => Math.abs(r.contribution)), 0.01);
  return (
    <Panel id="p-inflation" title="Ton inflation" hint="tes prix fixes (loyer, primes, abonnements) contre ceux d'il y a un an, pesés par ce qu'ils coûtent">
      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div>
          <div className="eyebrow">Ton panier fixe</div>
          <div className={cx("num mt-1 text-[24px] font-semibold", inf.pct > 0.05 ? "text-critical" : "text-good")}>{signedPct(inf.pct)}</div>
          <div className="text-[12px] text-muted">sur un an · {inf.count} engagements</div>
        </div>
        <div>
          <div className="eyebrow">La Suisse</div>
          <div className="num mt-1 text-[24px] font-semibold">{cpi.pct != null ? signedPct(cpi.pct) : "—"}</div>
          <div className="text-[12px] text-muted">indice des prix{cpi.month ? `, ${monthLabel(cpi.month)}` : ""}</div>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <div className="eyebrow">Ce que ça coûte</div>
          <div className="num mt-1 text-[24px] font-semibold">{signedChf(inf.delta, 0)}</div>
          <div className="text-[12px] text-muted">par an, aux prix d'aujourd'hui</div>
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ul className="min-w-0 space-y-2">
          {inf.rows.map((r) => (
            <li key={r.label} className="text-[13px]">
              <div className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 truncate">{r.label}</span>
                <span className="num shrink-0 text-muted">{chf(r.before, 2)} → {chf(r.now, 2)}</span>
                <span className={cx("num w-16 shrink-0 text-right font-medium", r.pct > 0.05 ? "text-critical" : r.pct < -0.05 ? "text-good" : "text-muted")}>{signedPct(r.pct)}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-surface-2">
                <div className={cx("h-full rounded-full", r.contribution > 0 ? "bg-critical" : "bg-good")}
                     style={{ width: `${(Math.abs(r.contribution) / top) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
        <div className="min-w-0">
          <div className="eyebrow mb-1">L'indice suisse, sur un an glissant</div>
          <Lines xs={xs} height={170} zero
                 series={[{ key: "cpi", name: "Suisse", color: "var(--ink-2)", values: cpi.monthly.map((m) => m.pct), width: 2 }]}
                 refs={[{ value: Number(inf.pct.toFixed(2)), color: "var(--critical)", label: "toi", dash: true }]}
                 format={(v) => `${v.toFixed(1)} %`}
                 tipFormat={(v) => signedPct(v)}
                 xLabel={(i) => monthLabel(cpi.monthly[i].month)}
                 xTicks={(w) => spreadTicks(xs.length, w, (i) => {
                   const [y, m] = cpi.monthly[i].month.split("-");
                   return `${MONTHS_SHORT[Number(m) - 1]} ${y.slice(2)}`;
                 }, 60)}
                 ariaLabel="Inflation suisse sur un an glissant, et la tienne" />
        </div>
      </div>
      <Note>
        La barre dit ce que chaque hausse pèse dans ton panier. Restent dehors les factures qui varient (l'électricité),
        les impôts (ils suivent le revenu) et les courses : le relevé en connaît les totaux, pas les prix.
        Source : <a href={cpi.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-accent">{cpi.source}<ExternalLink size={11} /></a>,
        {cpi.fetched ? ` rafraîchie le ${frDate(cpi.fetched)}` : " chiffres de l'app"}, jusqu'à {monthLabel(cpi.latest)}.
      </Note>
    </Panel>
  );
}

export function VersusSwitzerland({ h }: { h: Households }) {
  const max = Math.max(...h.rows.flatMap((r) => [r.mine, r.household]), 1);
  return (
    <Panel id="p-households" title="Toi et les ménages suisses"
           hint={`ton mois moyen (${monthLabel(h.first)} → ${monthLabel(h.last)}) contre le ménage suisse moyen, et ce ménage par personne`}>
      <ul className="space-y-3.5">
        {h.rows.map((r) => (
          <li key={r.label} className="text-[13px]">
            <div className="flex items-baseline gap-3">
              <span className="min-w-0 flex-1 truncate font-medium">{r.label}</span>
              <span className="num shrink-0 font-semibold">{chf(r.mine, 0)}</span>
              {r.vs_person != null && (
                <span title="contre le ménage suisse par personne"
                      className={cx("num w-14 shrink-0 text-right text-[12px]", r.vs_person > 0 ? "text-critical" : "text-good")}>
                  {signedPct(r.vs_person, 0)}
                </span>
              )}
            </div>
            <div className="relative mt-1.5 h-2.5 rounded-full bg-surface-2" role="img"
                 aria-label={`${r.label} : toi ${chf(r.mine, 0)}, par personne ${chf(r.person, 0)}, ménage ${chf(r.household, 0)} CHF par mois`}>
              <div className="absolute inset-y-0 left-0 rounded-full bg-[var(--s0)]" style={{ width: `${(r.mine / max) * 100}%` }} />
              <span className="absolute -top-1 h-[18px] w-0.5 rounded bg-ink" style={{ left: `${(r.person / max) * 100}%` }} title={`par personne : ${chf(r.person, 0)}`} />
              <span className="absolute -top-1 h-[18px] w-0.5 rounded bg-muted" style={{ left: `${(r.household / max) * 100}%` }} title={`ménage moyen : ${chf(r.household, 0)}`} />
            </div>
            <div className="mt-0.5 flex gap-3 text-[11.5px] text-muted">
              <span>par personne {chf(r.person, 0)}</span><span>ménage {chf(r.household, 0)}</span>
            </div>
          </li>
        ))}
      </ul>
      <Note>
        Le ménage suisse moyen compte {h.size.toFixed(2).replace(".", ",")} personnes. Une personne seule dépense plus qu'une tête de couple
        (le loyer et les abonnements ne se partagent pas) : la vérité est entre le trait vif (par personne) et le trait pâle (le ménage). Le pourcentage compare à la personne.
        Les achats divers (habits, meubles, électronique) n'ont pas d'équivalent net et restent dehors.
        Source : <a href={h.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-accent">{h.source}<ExternalLink size={11} /></a>.
      </Note>
    </Panel>
  );
}
