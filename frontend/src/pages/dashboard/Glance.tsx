/** The dashboard's readings at a glance: the month in progress against an
 * ordinary one, and each category against the window before. The figures
 * are the server's (`lookback.month_pace`, `api/dashboard._versus`). */
import { useState } from "react";
import { Link } from "react-router";

import { Lines, spreadTicks } from "@/charts/Lines";
import { Diverging } from "@/components/Diverging";
import { Dot, Note, Panel, cx } from "@/components/ui";
import { chf, frDay, plural, signedChf } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { useView } from "@/lib/url";

/** Where the month stands against an ordinary one, and where it would end. */
export function Pace({ data }: { data: Dashboard }) {
  const p = data.pace!;
  const xs = p.median.map((_, i) => i + 1);
  const over = p.vs_ordinary > 0;
  return (
    <Panel id="p-pace" title={p.done ? "Le mois, contre un mois ordinaire" : "Le mois en cours"}
           hint={`au ${p.day} sur ${p.days} jours · un mois ordinaire : médiane de ${p.span.label}`}>
      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <div className="eyebrow">Dépensé</div>
          <div className="num mt-1 text-[20px] font-semibold">{chf(p.spent, 0)}</div>
          <div className="text-[12px] text-muted">au {p.day}</div>
        </div>
        <div>
          <div className="eyebrow">Contre l'ordinaire</div>
          <div className={cx("num mt-1 text-[20px] font-semibold", over ? "text-critical" : "text-good")}>{signedChf(p.vs_ordinary, 0)}</div>
          <div className="text-[12px] text-muted">{chf(p.ordinary_now, 0)} d'habitude au même jour</div>
        </div>
        {!p.done && (
          <div className="col-span-2 sm:col-span-1">
            <div className="eyebrow">Fin de mois probable</div>
            <div className="num mt-1 text-[20px] font-semibold">≈ {chf(p.projected, 0)}</div>
            <div className="text-[12px] text-muted">si la suite suit l'ordinaire · {chf(p.ordinary_end, 0)} un mois ordinaire</div>
          </div>
        )}
      </div>
      <Lines xs={xs} height={190}
             band={{ low: p.low, high: p.high, color: "var(--ink-2)" }}
             series={[
               { key: "median", name: "Mois ordinaire", color: "var(--ink-2)", values: p.median, dash: true, width: 1.75 },
               { key: "now", name: "Ce mois", color: "var(--s0)", width: 2.5,
                 values: p.median.map((_, i) => (i < p.values.length ? p.values[i] : null)) },
             ]}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             xLabel={(i) => `le ${i + 1}`}
             xTicks={(w) => spreadTicks(p.days, w, (i) => String(i + 1), 40)}
             ariaLabel="Dépense cumulée du mois, contre un mois ordinaire" />
      <div className="mt-2 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><Dot color="var(--s0)" />ce mois</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-0 w-3 border-t-2 border-dashed border-ink-2" />mois ordinaire</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-3 rounded-sm bg-ink-2/20" />la moitié des mois</span>
      </div>
      {p.budgets.length > 0 && (
        <div className="mt-5 border-t border-hairline pt-4">
          <h3 className="mb-2 text-[14px] font-semibold">Budgets du mois</h3>
          <ul className="space-y-2.5">
            {p.budgets.map((b) => {
              const width = Math.min((b.spent / b.budget) * 100, 100);
              const mark = Math.min((b.pace / b.budget) * 100, 100);
              const ahead = b.spent > b.pace + 0.5;
              return (
                <li key={b.category} className="text-[13px]">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="truncate">{b.category}</span>
                    <span className="num shrink-0"><b>{chf(b.spent, 0)}</b> <span className="text-muted">/ {chf(b.budget, 0)}</span></span>
                  </div>
                  <div className="relative mt-1 h-2 rounded-full bg-surface-2" title={`au rythme du mois : ${chf(b.pace, 0)} CHF`}>
                    <div className={cx("h-full rounded-full", b.spent > b.budget ? "bg-critical" : ahead ? "bg-warn" : "bg-good")} style={{ width: `${width}%` }} />
                    {!p.done && <span className="absolute -top-0.5 h-3 w-0.5 rounded bg-ink" style={{ left: `${mark}%` }} />}
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">
                    {b.spent > b.budget ? `dépassé de ${chf(b.spent - b.budget, 0)} CHF`
                      : ahead ? `en avance sur le mois : ${chf(b.pace, 0)} attendus au ${p.day}`
                      : `reste ${chf(b.budget - b.spent, 0)} CHF`}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <Note>La fin de mois probable ajoute à ce qui est dépensé ce qu'un mois ordinaire dépense encore après ce jour. {p.budgets.length > 0 && "Le trait d'un budget marque la part du mois écoulée."}</Note>
    </Panel>
  );
}

/** Each category against the window before: the why of the spending tile. */
export function Versus({ data }: { data: Dashboard }) {
  const { pageHref } = useView();
  const [all, setAll] = useState(false);
  const rows = all ? data.versus : data.versus.slice(0, 6);
  if (!data.versus.length) return null;
  return (
    <Panel id="p-versus" title={`Par rapport à ${data.previous.label}`}
           hint="chaque catégorie contre la même durée juste avant ; une catégorie ouvre ses transactions">
      <Diverging ariaLabel="Variation de chaque catégorie contre la période précédente"
                 rows={rows.map((r) => ({ key: r.category, label: r.category, before: r.before, now: r.now, delta: r.delta,
                                          color: `var(--s${r.slot})`,
                                          to: `${pageHref("/transactions")}${pageHref("/transactions").includes("?") ? "&" : "?"}category=${encodeURIComponent(r.category)}` }))} />
      {data.versus.length > 6 && (
        <button type="button" onClick={() => setAll(!all)} className="mt-2 text-[12.5px] font-medium text-accent hover:underline">
          {all ? "Moins" : `Les ${data.versus.length} catégories`}
        </button>
      )}
    </Panel>
  );
}

/** The next due dates of the month ahead, from today: the page `/a-venir`
 * has the rest, and why. */
export function Soon({ data }: { data: Dashboard }) {
  const s = data.soon!;
  return (
    <Panel id="p-soon" title="À venir" hint={`d'ici le ${frDay(s.month.until, false)} : ${chf(s.month.out, 0)} CHF en ${plural(s.month.count, "échéance")}`}
           actions={<Link to="/a-venir" className="text-[13px] font-medium text-accent no-underline hover:underline">Tout voir</Link>}>
      <ul className="divide-y divide-hairline">
        {s.next.map((r) => (
          <li key={r.day + r.label} className="flex items-center gap-3 py-2 text-[13.5px]">
            <span className="num w-16 shrink-0 text-muted">{frDay(r.day, false)}</span>
            <span className="min-w-0 flex-1 truncate">{r.label}</span>
            <span className="num shrink-0 font-medium">{r.variable ? "≈ " : ""}{chf(r.amount, 0)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
