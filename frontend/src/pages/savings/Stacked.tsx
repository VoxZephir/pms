/* Is the stacked fund doing its job? RSST against what it promises: a franc
 * of S&P 500 and a franc of managed futures, the second financed at the
 * T-bill rate. Every figure comes from `stacked.py`; the page only lays
 * them out. */

import { useMemo, useState } from "react";

import { Lines, monthTicks } from "@/charts/Lines";
import { Callout, Dot, Note, Panel, Segmented, cx } from "@/components/ui";
import { chf, day, frDate, signedRate } from "@/lib/format";
import type { Savings, StackedLine, TrendPeriods as TrendPeriodsData, TrendRead } from "@/lib/savings";

const LINES: { key: StackedLine; name: string; color: string; dash?: boolean; width: number; why: string }[] = [
  { key: "fund", name: "RSST", color: "var(--s0)", width: 2.5, why: "le fonds, dividendes réinvestis" },
  { key: "replica", name: "Réplique", color: "var(--ink-2)", dash: true, width: 1.75,
    why: "S&P 500 + managed futures − bons du Trésor : ce que le fonds promet" },
  { key: "stocks", name: "S&P 500", color: "var(--s2)", width: 1.5, why: "la jambe actions seule" },
  { key: "trend", name: "DBMF", color: "var(--s3)", width: 1.5, why: "managed futures : réplique l'indice SG CTA" },
  { key: "leg", name: "Jambe trend de RSST", color: "var(--s4)", width: 1.5,
    why: "RSST − S&P 500 + bons du Trésor : le trend que le fonds a vraiment livré" },
];

const TONE: Record<string, string> = { good: "text-good", warn: "text-warn", bad: "text-critical" };

function rateTone(v: number | null | undefined) {
  if (v == null) return "";
  return v > 0.0005 ? "text-good" : v < -0.0005 ? "text-critical" : "";
}

export function StackedFund({ s }: { s: Savings }) {
  const pack = s.stacked!;
  // Local, like "Empilé" on the curve: the same fund seen over another span,
  // and "since launch" is no window the page could carry.
  // Until a choice is made, a window too short to say anything (the
  // current month, the default) gives way to the fund's whole history.
  const [choice, setSpan] = useState<"window" | "launch" | null>(null);
  const span = choice ?? (pack.window?.short && pack.launch && !pack.launch.short ? "launch" : "window");
  const [hidden, setHidden] = useState<Set<string>>(() => new Set(["stocks"]));
  const st = (span === "launch" ? pack.launch : pack.window) ?? pack.window;
  const rows = useMemo(() => st?.rows ?? [], [st]);
  const xs = useMemo(() => rows.map((r) => day(r.date).getTime()), [rows]);

  const title = "RSST fait-il son travail ?";
  if (pack.missing || !st) {
    return (
      <Panel id="p-stacked" title={title}>
        <Note className="mt-0">Les séries du fonds et de ses composantes ne sont pas capturées : « Rafraîchir », ou <code>python -m pms --benchmarks</code>.</Note>
        {pack.periods && <TrendPeriods p={pack.periods} />}
      </Panel>
    );
  }
  const toggle = pack.launch && !pack.launch.short && (
    <Segmented size="sm" label="Période du fonds" value={span} onChange={(id) => setSpan(id as "window" | "launch")}
               options={[{ id: "window", label: "Fenêtre" },
                         { id: "launch", label: "Depuis le lancement", title: `depuis le ${frDate(pack.launch.since!)}` }]} />
  );
  if (st.short) {
    return (
      <Panel id="p-stacked" title={title} actions={toggle}>
        <Note className="mt-0">
          {st.days ?? 0} jours de cotation sur la fenêtre : trop peu pour une volatilité ou une régression (40 au moins).
          {toggle && " « Depuis le lancement » lit le fonds sur toute son histoire."}
        </Note>
        {pack.periods && <TrendPeriods p={pack.periods} />}
      </Panel>
    );
  }

  const stats = st.stats!;
  const tr = st.tracking!;
  const fit = st.regression;
  const yearly = stats.fund.annual != null;
  const shown = (k: StackedLine) => (yearly ? stats[k].annual : stats[k].total);
  const pos = pack.position;

  return (
    <Panel id="p-stacked" title={title} actions={toggle}
           hint={`${frDate(st.from!)} → ${frDate(st.to!)} · ${st.days} jours de cotation · en CHF`}>
      <ul className="mb-4 space-y-1.5 text-[13.5px]">
        {(st.verdict ?? []).map((v) => (
          <li key={v.text} className="flex gap-2">
            <span className={cx("font-semibold", TONE[v.tone])} aria-hidden>{v.tone === "good" ? "✓" : v.tone === "warn" ? "~" : "✗"}</span>
            <span>{v.text}</span>
          </li>
        ))}
      </ul>

      <Lines xs={xs} height={240} zero={false}
             series={LINES.filter((l) => !hidden.has(l.key)).map((l) => ({
               key: l.key, name: l.name, color: l.color, dash: l.dash, width: l.width,
               values: rows.map((r) => r[l.key]),
             }))}
             format={(v) => v.toFixed(0)}
             tipFormat={(v) => v.toFixed(1)}
             xLabel={(i) => frDate(rows[i].date)}
             xTicks={(w) => monthTicks(xs, w, 64)}
             refs={[{ value: 100, color: "var(--axis)", dash: true }]}
             ariaLabel="RSST, sa réplique et ses composantes, base 100" />
      <div className="mt-3 flex flex-wrap gap-2">
        {LINES.map((l) => {
          const off = hidden.has(l.key);
          return (
            <button key={l.key} type="button" aria-pressed={!off} title={l.why}
                    onClick={() => setHidden((h) => { const n = new Set(h); if (off) n.delete(l.key); else n.add(l.key); return n; })}
                    className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] transition",
                      off ? "border-hairline text-muted line-through" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
              {l.dash ? <i className="h-0 w-3 border-t-2 border-dashed" style={{ borderColor: l.color }} /> : <Dot color={l.color} />}
              {l.name}
            </button>
          );
        })}
      </div>

      <div className="-mx-4 mt-4 overflow-x-auto sm:-mx-5">
        <table className="w-full min-w-[620px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-hairline text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted">
              <th className="px-4 py-2 text-left sm:px-5" />
              <th className="px-3 py-2 text-right">{yearly ? "Par an" : "Période"}</th>
              <th className="px-3 py-2 text-right">Volatilité</th>
              <th className="px-3 py-2 text-right">Pire baisse</th>
              <th className="px-3 py-2 text-right">Corr. S&amp;P</th>
            </tr>
          </thead>
          <tbody>
            {LINES.map((l) => (
              <tr key={l.key} className="border-b border-hairline last:border-0">
                <td className="px-4 py-2 sm:px-5">
                  <span className="inline-flex items-center gap-1.5 font-medium">
                    {l.dash ? <i className="h-0 w-3 border-t-2 border-dashed" style={{ borderColor: l.color }} /> : <Dot color={l.color} />}{l.name}
                  </span>
                  <div className="text-[11.5px] text-muted">{l.why}</div>
                </td>
                <td className={cx("num whitespace-nowrap px-3 py-2 text-right", rateTone(shown(l.key)))}>{signedRate(shown(l.key))}</td>
                <td className="num whitespace-nowrap px-3 py-2 text-right">{(stats[l.key].vol * 100).toFixed(1)} %</td>
                <td className="num whitespace-nowrap px-3 py-2 text-right text-critical">{signedRate(stats[l.key].drawdown)}</td>
                <td className="num whitespace-nowrap px-3 py-2 text-right">{stats[l.key].corr_stocks == null ? "—" : stats[l.key].corr_stocks!.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Écart à la réplique" value={signedRate(yearly ? tr.difference_pa : tr.difference)}
              tone={rateTone(yearly ? tr.difference_pa : tr.difference)}
              sub={yearly ? "par an, frais compris" : "sur la période, frais compris"} />
        <Tile label="Écart de suivi" value={`${(tr.error_pa * 100).toFixed(1)} %`}
              sub={`par an · corrélation ${tr.corr == null ? "—" : tr.corr.toFixed(2)}`} />
        {fit && <Tile label="Bêtas actions · trend" value={`${fit.beta_stocks.toFixed(2)} · ${fit.beta_trend.toFixed(2)}`}
                      sub={`1 · 1 visés · R² ${fit.r2 == null ? "—" : fit.r2.toFixed(2)}`} />}
        {st.falls && <Tile label="Mois où le S&P 500 baisse" value={`${st.falls.months} sur ${st.falls.of}`}
                           sub={`en moyenne : S&P ${signedRate(st.falls.stocks)}, RSST ${signedRate(st.falls.fund)}, trend ${signedRate(st.falls.leg)} (positive ${st.falls.leg_up} fois)`} />}
      </div>

      {pack.periods && <TrendPeriods p={pack.periods} />}

      {pos && (
        <Callout className="mt-4" title="Ta position">
          {chf(pos.value, 0)} CHF à la dernière capture IBKR ·{" "}
          <span className={rateTone(pos.pnl)}>{pos.pnl >= 0 ? "+" : "−"}{chf(Math.abs(pos.pnl), 0)} CHF ({pos.pnl_pct >= 0 ? "+" : ""}{pos.pnl_pct.toFixed(1)} %)</span> latents,
          contre le prix moyen d'achat. Le panneau juge le fonds, pas le moment de tes achats.
        </Callout>
      )}

      <Note>
        <b className="text-ink-2">Comment lire.</b> Le fonds promet, pour chaque franc, un franc d'actions américaines et un franc de managed futures ;
        le second est financé au taux des bons du Trésor. La réplique fait ce calcul jour par jour ; en francs, le change s'y annule exactement.
        La jambe trend retire au fonds son franc d'actions : c'est le trend qu'il a vraiment livré. Le fonds managed futures (DBMF) est un repère,
        pas le modèle de RSST : un écart dit aussi que les deux modèles trend diffèrent, pas seulement que le fonds coûte.
        Le bêta trend mesuré contre ce repère est tiré vers le bas pour la même raison.
        {pack.sources && <> Sources : {Object.values(pack.sources).join(" ; ")}.</>}
      </Note>
    </Panel>
  );
}

/** A return already in % (12.3), signed. */
function sp(v: number) {
  if (Math.abs(v) < 0.05) return "0.0 %";
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} %`;
}

function pctTone(v: number) {
  return v >= 0.05 ? "text-good" : v <= -0.05 ? "text-critical" : "";
}

/** The pocket against its index, DBMF against its own, above cash, period
 * by period then cumulated: the skill's reading, figures gathered by hand
 * since SG keeps its index histories private. */
function TrendPeriods({ p }: { p: TrendPeriodsData }) {
  const cols: { key: keyof TrendRead; label: string; gap?: boolean }[] = [
    { key: "pocket", label: "Poche trend RSST" },
    { key: "sg_trend", label: "SG Trend" },
    { key: "gap_trend", label: "Poche − SG Trend", gap: true },
    { key: "dbmf", label: "DBMF" },
    { key: "sg_cta", label: "SG CTA" },
    { key: "gap_cta", label: "DBMF − SG CTA", gap: true },
  ];
  const cells = (r: TrendRead, strong = false) => cols.map((c) => (
    <td key={c.key} className={cx("num whitespace-nowrap px-3 py-2 text-right", c.gap && pctTone(r[c.key]), strong && "font-semibold")}>{sp(r[c.key])}</td>
  ));
  return (
    <div id="stacked-periods" className="mt-5">
      <h3 className="text-[14px] font-semibold text-ink">Contre les indices SG, en excès du cash</h3>
      <p className="mt-0.5 text-[12.5px] text-muted">
        Rendements totaux en USD par période ; la poche est RSST moins le S&amp;P 500 TR, nette des frais du fonds ; les indices et DBMF moins les bons du Trésor.
      </p>
      <div className="-mx-4 mt-2 overflow-x-auto sm:-mx-5">
        <table className="w-full min-w-[680px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-hairline text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted">
              <th className="px-4 py-2 text-left sm:px-5">Période</th>
              {cols.map((c) => <th key={c.key} className="px-3 py-2 text-right">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {p.rows.map((r) => (
              <tr key={r.period} className="border-b border-hairline" title={r.sources}>
                <td className="px-4 py-2 sm:px-5">{r.period}</td>
                {cells(r)}
              </tr>
            ))}
            <tr className="border-t-2 border-hairline-2">
              <td className="px-4 py-2 font-semibold sm:px-5">Cumul</td>
              {cells(p.total, true)}
            </tr>
          </tbody>
        </table>
      </div>
      <Note>
        SG ne publie pas l'historique de ses indices : ces chiffres sont rassemblés à la main (skill <code>analyse-poche-trend-rsst</code>),
        la source de chaque ligne au survol. {p.estimated && "Certaines cases sont déduites ou estimées : environ ±1 point par chiffre. "}
        {p.note}
      </Note>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-hairline p-3">
      <div className="eyebrow">{label}</div>
      <div className={cx("num mt-1 text-[18px] font-semibold", tone)}>{value}</div>
      <div className="mt-0.5 text-[12px] text-muted">{sub}</div>
    </div>
  );
}
