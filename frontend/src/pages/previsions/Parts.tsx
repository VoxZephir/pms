/** The net worth taken apart: its layers by pocket or by asset class, and
 * what each piece brings from today to the horizon. Every figure is the
 * server's (`views.previsions._parts`); this file lays them out. */
import type { LineSeries } from "@/charts/Lines";
import { Bridge, type BridgeStep } from "@/components/Bridge";
import { Note, Panel, cx } from "@/components/ui";
import { chf, signedChf } from "@/lib/format";
import type { Previsions, Split, WealthParts } from "@/lib/previsions";

export type SplitMode = "total" | "pockets" | "classes";

export const slotColor = (slot: number | null) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");

/** The layers of a split as stacked series: solid where measured, lighter
 * and dashed where projected, sharing today's point. Null when a layer goes
 * below zero -- a stack cannot draw it honestly, the caller draws lines. */
export function stacked(sp: Split, n: number): LineSeries[] | null {
  const points = [...sp.observed, ...sp.projected];
  if (points.some((p) => Object.values(p).some((v) => v < -0.5))) return null;
  let below = points.map(() => 0);
  const out: LineSeries[] = [];
  sp.series.forEach((s) => {
    const top = points.map((p, i) => below[i] + (p[s.key] ?? 0));
    const color = slotColor(s.slot);
    const seen = (arr: number[]) => arr.map((v, i) => (i < n ? v : null));
    const ahead = (arr: number[]) => arr.map((v, i) => (i >= n - 1 ? v : null));
    out.push({ key: `${s.key}:seen`, name: s.name, color, values: seen(top), fillTo: seen(below), silent: true, width: 1.25 });
    out.push({ key: `${s.key}:ahead`, name: s.name, color, values: ahead(top), fillTo: ahead(below), silent: true, width: 1.25, dash: true });
    below = top;
  });
  return out;
}

/** The same layers, one line each -- when a stack would lie. */
export function lines(sp: Split, n: number): LineSeries[] {
  const points = [...sp.observed, ...sp.projected];
  return sp.series.flatMap((s) => {
    const color = slotColor(s.slot);
    const all = points.map((p) => p[s.key] ?? 0);
    return [
      { key: `${s.key}:seen`, name: s.name, color, values: all.map((v, i) => (i < n ? v : null)), silent: true },
      { key: `${s.key}:ahead`, name: s.name, color, values: all.map((v, i) => (i >= n - 1 ? v : null)), silent: true, dash: true },
    ];
  });
}

/** Each layer at a point, for the tooltip, largest first. */
export function tipParts(sp: Split, n: number, i: number) {
  const p = i < n ? sp.observed[i] : sp.projected[i - n];
  if (!p) return [];
  return sp.series
    .map((s) => ({ name: s.name, value: `${chf(p[s.key] ?? 0, 0)} CHF`, color: slotColor(s.slot), raw: p[s.key] ?? 0 }))
    .sort((a, b) => b.raw - a.raw)
    .map(({ raw: _raw, ...row }) => row);
}

/** Under the chart: each layer today and at the horizon, and its share then. */
export function SplitLegend({ sp, horizon }: { sp: Split; horizon: string }) {
  const now = sp.observed[sp.observed.length - 1] ?? {};
  const then = sp.projected[sp.projected.length - 1] ?? {};
  const total = Object.values(then).reduce((a, v) => a + v, 0);
  return (
    <div className="mt-3 grid max-w-lg grid-cols-1 gap-y-1.5 text-[12.5px]">
      {sp.series.map((s) => (
        <div key={s.key} className="flex min-w-0 items-center gap-2">
          <i className="inline-block h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: slotColor(s.slot) }} />
          <span className="min-w-0 flex-1 truncate">{s.name}</span>
          <span className="num text-muted">{chf(now[s.key] ?? 0, 0)}</span>
          <span className="text-muted">→</span>
          <span className="num font-medium">{chf(then[s.key] ?? 0, 0)}</span>
          {total > 0 && <span className="num w-10 text-right text-muted">{Math.round(((then[s.key] ?? 0) / total) * 100)} %</span>}
        </div>
      ))}
      <p className="text-[11.5px] text-muted">aujourd'hui → dans {horizon} · part à l'horizon</p>
    </div>
  );
}

/** From today's net worth to the horizon's, one step per cause. */
function WealthBridge({ parts, horizon }: { parts: WealthParts; horizon: string }) {
  const steps: BridgeStep[] = parts.flows.map((f) => ({
    key: f.key, label: f.label, amount: f.amount,
    color: f.key === "income" ? "var(--good)"
      : f.slot != null ? slotColor(f.slot)
      : f.amount < 0 ? "var(--critical)" : "var(--good)",
  }));
  return <Bridge start={{ label: "Aujourd'hui", value: parts.start }} steps={steps}
                 end={{ label: `Dans ${horizon}`, value: parts.end }}
                 ariaLabel="Du patrimoine d'aujourd'hui à celui de l'horizon" />;
}

/** "D'où viendra le patrimoine": the bridge, then each pocket's account. */
export function Contributions({ d }: { d: Previsions }) {
  const parts = d.wealth!.parts;
  const view = d.wealth_views.find((v) => v.id === d.wealth_view);
  const total = parts.table.reduce((a, t) => a + t.end, 0);
  // A pocket that holds nothing now and receives nothing is not one the
  // account holder has.
  const table = parts.table.filter((t) => [t.start, t.paid, t.end].some((v) => Math.abs(v) >= 0.5));
  return (
    <Panel title="Ce qui fera le patrimoine"
           hint={<>de {chf(parts.start, 0)} à {chf(parts.end, 0)} CHF en {d.horizon_label}{d.wealth_view !== "all" && view ? ` · ${view.label.toLowerCase()}` : ""}</>}>
      <WealthBridge parts={parts} horizon={d.horizon_label} />
      <div className="mt-5 overflow-x-auto rounded-xl border border-hairline">
        <table className="w-full min-w-[30rem] text-[13px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-muted">
              <th className="px-3 py-2 font-semibold">Poche</th>
              <th className="px-3 py-2 text-right font-semibold">Aujourd'hui</th>
              <th className="px-3 py-2 text-right font-semibold" title="versé depuis le cash, ou sorti vers les placements">Versé</th>
              <th className="px-3 py-2 text-right font-semibold">Rendement</th>
              <th className="px-3 py-2 text-right font-semibold">Dans {d.horizon_label}</th>
              <th className="px-3 py-2 text-right font-semibold">Part</th>
            </tr>
          </thead>
          <tbody>
            {table.map((t) => (
              <tr key={t.key} className="border-t border-hairline">
                <td className="px-3 py-2"><span className="inline-flex items-center gap-2">
                  <i className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: slotColor(t.slot) }} />{t.name}</span></td>
                <td className="num px-3 py-2 text-right text-ink-2">{chf(t.start, 0)}</td>
                <td className={cx("num px-3 py-2 text-right", t.paid > 0 ? "text-good" : t.paid < 0 ? "text-ink-2" : "text-muted")}>{Math.abs(t.paid) >= 0.5 ? signedChf(t.paid, 0) : "—"}</td>
                <td className={cx("num px-3 py-2 text-right", t.growth > 0 ? "text-good" : t.growth < 0 ? "text-critical" : "text-muted")}>
                  {t.key === "swiss" ? "—" : Math.abs(t.growth) >= 0.5 ? signedChf(t.growth, 0) : "0"}</td>
                <td className="num px-3 py-2 text-right font-semibold">{chf(t.end, 0)}</td>
                <td className="num px-3 py-2 text-right text-muted">{total > 0 ? `${Math.round((t.end / total) * 100)} %` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        Les revenus et la dépense viennent du plan ; le rendement {parts.rated
          ? (parts.own.length ? "applique à chaque poche son barème : le sien quand elle en a un, le barème commun sinon" : "applique votre barème à chaque poche investie, le même taux pour toutes")
          : "est nul : aucun barème n'est déclaré, les placements restent à leur valeur"}.
        {parts.moved > 0.5 && ` ${chf(parts.moved, 0)} CHF passent du cash aux placements : un déplacement, pas un gain — ils sortent d'une ligne et entrent dans l'autre.`}
        {" "}Par classe d'actifs, chaque poche garde sa composition d'aujourd'hui.
      </Note>
    </Panel>
  );
}
