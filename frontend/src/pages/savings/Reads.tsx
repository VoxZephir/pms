/** The savings read beyond the headline: each pocket as a card, where the
 * change came from, the months one by one, the falls from a high. Every
 * figure is the server's (`views/savings_reads.py`); this file lays them
 * out and draws them. */
import { X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { Lines, monthTicks } from "@/charts/Lines";
import { Bridge } from "@/components/Bridge";
import { Num } from "@/components/Num";
import { Card, Dot, Note, Panel, Segmented, cx } from "@/components/ui";
import { day, frDate, signedChf, signedRate } from "@/lib/format";
import type { PocketKey, Savings } from "@/lib/savings";
import { useView } from "@/lib/url";

export function tone(v: number | null | undefined, eps = 0.0005) {
  if (v == null) return "";
  return v >= eps ? "text-good" : v <= -eps ? "text-critical" : "";
}

const slotColor = (s: Savings, pocket: PocketKey) => {
  const slot = s.reads.slots[pocket];
  return slot != null ? `var(--s${slot})` : "var(--unsorted)";
};

const SHORT: Record<string, string> = { total: "Tout", swissquote: "Swissquote", ibkr: "IBKR", finpension: "3a", crypto: "Crypto", titres: "Titres" };

/* ----------------------------------------------------------- pocket cards */

/** A pocket's line in a few points: its shape, not its scale. */
function Spark({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, 34 - ((v - lo) / span) * 30]);
  const line = pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  return (
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" className="h-9 w-full" aria-hidden>
      <polygon points={`0,36 ${line} 100,36`} fill={color} opacity={0.12} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.75} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

/** One card per pocket: what it holds, its line over the window, what it
 * made and how. A card opens the pocket; the chosen one says how to leave. */
export function PocketCards({ s }: { s: Savings }) {
  const { href } = useView();
  const rows = s.pockets.filter((r) => r.pocket !== "total");
  const perYear = s.rate === "annual";
  const mwr = s.perf === "mwr";
  return (
    <div className={cx("grid gap-3 sm:gap-4", rows.length >= 4 ? "grid-cols-2 lg:grid-cols-4" : "grid-cols-2 sm:grid-cols-3")}
         aria-label="Les poches">
      {rows.map((r) => {
        const chosen = s.focus === r.pocket;
        const rate = mwr ? (perYear && r.mwr_pa != null ? r.mwr_pa : r.mwr) : (perYear && r.twr_pa != null ? r.twr_pa : r.twr);
        const color = slotColor(s, r.pocket);
        return (
          <Card key={r.pocket} data-pocket={r.pocket}
                className={cx("relative p-4 transition", chosen ? "ring-2 ring-accent" : "hover:bg-surface-2/40")}>
            <Link to={href({ focus: chosen ? null : r.pocket })} preventScrollReset aria-current={chosen ? "true" : undefined}
                  className="absolute inset-0 rounded-[inherit]" aria-label={chosen ? `Revenir à toute l'épargne` : `Ouvrir ${r.name}`} />
            <div className="flex items-center gap-2 text-[13px]">
              <Dot color={color} />
              <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
              {chosen ? <X size={14} className="text-muted" aria-hidden />
                : r.share != null && <span className="num text-[12px] text-muted">{r.share.toFixed(0)} %</span>}
            </div>
            <div className="mt-1.5 flex items-baseline gap-1 text-[22px] font-semibold leading-none tracking-[-0.025em]">
              <Num value={r.value} className="num" /><span className="text-[11.5px] font-medium tracking-normal text-muted">CHF</span>
            </div>
            <div className="mt-2"><Spark values={s.reads.sparks[r.pocket] ?? []} color={color} /></div>
            <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-2 text-[12.5px]">
              {r.pocket === "swissquote" ? (
                <><span className="text-muted">entrées nettes</span><b className="num">{signedChf(r.put_in, 0)}</b></>
              ) : (
                <>
                  <b className={cx("num", tone(r.gain, 0.5))}>{signedChf(r.gain, 0)}</b>
                  <span className={cx("num", tone(rate))}>{signedRate(rate)}{perYear && (mwr ? r.mwr_pa : r.twr_pa) != null ? " /an" : ""}</span>
                </>
              )}
            </div>
            {r.pocket !== "swissquote" && Math.abs(r.put_in) >= 0.5 && (
              <div className="mt-0.5 text-[11.5px] text-muted">
                {r.pocket === "titres" ? "réévaluation et dividendes" : <>dont {signedChf(r.put_in, 0)} versés</>}
              </div>
            )}
            {r.pocket === "finpension" && <div className="mt-0.5 text-[11.5px] text-muted">estimé entre deux relevés</div>}
          </Card>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- bridge */

/** From the total at the start to the total at the end: what was set aside,
 * then what each pocket earned. The steps add up to the headline. */
export function WhereFrom({ s }: { s: Savings }) {
  const b = s.reads.bridge;
  const steps = b.steps.map((st) => ({
    key: st.key, label: st.label, amount: st.amount,
    color: st.key === "saved" ? "var(--ink-2)" : slotColor(s, st.key as PocketKey),
    title: st.key === "saved" ? "ce qui est entré moins ce qui a été dépensé : l'argent mis de côté" : undefined,
  }));
  const gain = b.steps.filter((st) => st.key !== "saved").reduce((a, st) => a + st.amount, 0);
  const saved = b.steps.find((st) => st.key === "saved")?.amount ?? 0;
  return (
    <Panel id="p-bridge" title="D'où vient la variation"
           hint={`du ${frDate(s.period.start)} au ${frDate(s.period.end)} · toute l'épargne`}>
      <Bridge start={{ label: "Au début", value: b.start }} steps={steps}
              end={{ label: "À la fin", value: b.end }} ariaLabel="De l'épargne du début de la période à celle de la fin" />
      <Note>
        {Math.abs(saved) >= 0.5 && Math.abs(gain) >= 0.5
          ? <>Mis de côté : ce qui est entré moins ce qui a été dépensé. Le reste est ce que les placements ont fait.
            Un virement d'une poche à l'autre n'est pas une marche : il sort de l'une et entre dans l'autre.</>
          : "Un virement d'une poche à l'autre n'est pas une marche : il sort de l'une et entre dans l'autre."}
      </Note>
    </Panel>
  );
}

/* ------------------------------------------------------------ month grid */

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const MONTH_NAMES = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

const MEASURED: PocketKey[] = ["ibkr", "finpension", "crypto", "total"];

function usePocketChoice(s: Savings, available: PocketKey[]) {
  // The total is diluted by the current account: a pocket that is invested
  // says more, unless one is chosen above.
  const fallback = s.focus !== "total" && available.includes(s.focus as PocketKey) ? (s.focus as PocketKey)
    : available.includes("ibkr") ? "ibkr" : available[available.length - 1];
  const [picked, setPicked] = useState<PocketKey | null>(null);
  const pocket = picked && available.includes(picked) ? picked : fallback;
  return [pocket, setPicked] as const;
}

function PocketSwitch({ available, value, onChange }: { available: PocketKey[]; value: PocketKey; onChange: (p: PocketKey) => void }) {
  if (available.length < 2) return null;
  return <Segmented size="sm" label="Poche mesurée" value={value} onChange={onChange}
                    options={available.map((p) => ({ id: p, label: SHORT[p] ?? p }))} />;
}

/** The time-weighted return of each month, a year a row: the months a year
 * is made of, and which ones counted. */
export function MonthGrid({ s }: { s: Savings }) {
  const available = MEASURED.filter((p) => s.reads.months[p]);
  const [pocket, setPocket] = usePocketChoice(s, available);
  const m = s.reads.months[pocket];
  const scale = useMemo(() => {
    const all = (m?.years ?? []).flatMap((y) => y.months.filter((v): v is number => v != null).map(Math.abs));
    return Math.max(0.02, ...all);
  }, [m]);
  if (!m || available.length === 0) return null;
  const fill = (v: number | null) => {
    if (v == null) return undefined;
    const pct = Math.round(Math.min(Math.abs(v) / scale, 1) * 55 + (Math.abs(v) >= 0.0005 ? 8 : 0));
    return `color-mix(in srgb, ${v >= 0 ? "var(--good)" : "var(--critical)"} ${pct}%, transparent)`;
  };
  const label = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0)}`;
  return (
    <Panel id="p-months" title="Mois par mois"
           hint={`${m.name}${m.since ? ` depuis le ${frDate(m.since)}` : ""} · rendement de chaque mois, versements retirés (TWR)`}
           actions={<PocketSwitch available={available} value={pocket} onChange={setPocket} />}>
      <div className="-mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5">
        <table className="w-full min-w-[500px] border-separate border-spacing-[3px] text-center text-[11.5px]" data-months={pocket}>
          <thead>
            <tr className="text-muted">
              <th className="w-12" />
              <th className="w-14 pr-2 text-right font-semibold">Année</th>
              {MONTHS.map((l, i) => <th key={i} className="font-medium" title={MONTH_NAMES[i]}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {m.years.map((y) => (
              <tr key={y.year}>
                <th className="pr-1 text-left font-semibold text-ink-2">{y.year}</th>
                <td className={cx("num pr-2 text-right text-[12.5px] font-semibold", tone(y.rate))}>{signedRate(y.rate)}</td>
                {y.months.map((v, i) => (
                  <td key={i} className={cx("num h-9 rounded-md", v == null ? "bg-surface-2/40" : "text-ink", y.partial[i] && "italic")}
                      style={{ background: fill(v) }}
                      title={v == null ? undefined : `${MONTH_NAMES[i]} ${y.year} : ${signedRate(v)}${y.partial[i] ? " (mois partiel)" : ""}`}>
                    {v == null ? "" : label(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-ink-2">
        {m.count > 0 && <span><b className="num">{m.up}</b> mois en hausse sur <b className="num">{m.count}</b></span>}
        {m.best && m.best.rate > 0 && <span>meilleur : {MONTH_NAMES[m.best.month - 1]} {m.best.year} <b className="num text-good">{signedRate(m.best.rate)}</b></span>}
        {m.worst && m.worst.rate < 0 && <span>pire : {MONTH_NAMES[m.worst.month - 1]} {m.worst.year} <b className="num text-critical">{signedRate(m.worst.rate)}</b></span>}
      </div>
      <Note>En %. Les mois se chaînent en l'année, les années en la période : un mois coupé par la fenêtre est en italique et ne compte que les jours affichés.
        {pocket === "total" && " L'épargne totale compte le compte courant, à rendement nul : ses mois sont dilués d'autant."}
        {pocket === "finpension" && " Le 3a est estimé entre deux relevés par des indices de référence."}</Note>
    </Panel>
  );
}

/* ----------------------------------------------------------------- falls */

/** How far each day stood below the last high: the falls a pocket went
 * through, and how long the deepest took to make good. */
export function Falls({ s }: { s: Savings }) {
  const available = MEASURED.filter((p) => s.reads.drawdowns[p]);
  const [pocket, setPocket] = usePocketChoice(s, available);
  const d = s.reads.drawdowns[pocket];
  const xs = useMemo(() => (d?.rows ?? []).map((r) => day(r.date).getTime()), [d]);
  if (!d || available.length === 0) return null;
  const w = d.worst;
  return (
    <Panel id="p-falls" title="Baisses depuis le plus haut"
           hint={`${d.name}${d.since ? ` depuis le ${frDate(d.since)}` : ""} · chaque jour, l'écart au plus haut atteint jusque-là`}
           actions={<PocketSwitch available={available} value={pocket} onChange={setPocket} />}>
      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <div className="eyebrow">Pire baisse</div>
          <div className={cx("num mt-1 text-[20px] font-semibold", w && "text-critical")}>{w ? signedRate(w.depth) : "aucune"}</div>
          {w && <div className="text-[12px] text-muted">du {frDate(w.peak)} au {frDate(w.trough)}</div>}
        </div>
        <div>
          <div className="eyebrow">Remontée</div>
          <div className="mt-1 text-[20px] font-semibold">{w ? (w.recovered ? <span className="num">{w.days} j</span> : "pas encore") : "—"}</div>
          {w && <div className="text-[12px] text-muted">{w.recovered ? `retour au plus haut le ${frDate(w.recovered)}` : `${w.days} jours depuis le plus haut`}</div>}
        </div>
        <div className="col-span-2 sm:col-span-1">
          <div className="eyebrow">Aujourd'hui</div>
          <div className={cx("num mt-1 text-[20px] font-semibold", d.current < -0.0005 && "text-critical")}>
            {d.current < -0.0005 ? signedRate(d.current) : "au plus haut"}</div>
          <div className="text-[12px] text-muted">au {frDate(s.period.end)}</div>
        </div>
      </div>
      {w ? (
        <Lines xs={xs} height={170} zero
               series={[{ key: "dd", name: "Écart au plus haut", color: "var(--critical)", area: true, width: 1.75,
                          values: d.rows.map((r) => r.dd * 100) }]}
               format={(v) => `${v.toFixed(0)} %`}
               tipFormat={(v) => `${v.toFixed(1)} %`}
               xLabel={(i) => frDate(d.rows[i].date)}
               xTicks={(width) => monthTicks(xs, width, 64)}
               ariaLabel="Écart au plus haut, jour par jour" />
      ) : <p className="text-[13px] text-muted">Aucune baisse sur la période : chaque jour a égalé ou dépassé le précédent plus haut.</p>}
      <Note>Mesuré sur la performance (TWR) : un retrait n'est pas une baisse, un versement n'efface pas une perte.</Note>
    </Panel>
  );
}
