/** Is there enough cash at time t, and where does it all end up? The cash
 * month by month, net worth measured then projected, whole plans compared
 * as scenarios -- and the plan itself, editable in place. */
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Lines, spreadTicks } from "@/charts/Lines";
import { Input } from "@/components/Form";
import { MonthlyProfile } from "@/components/MonthlyProfile";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageState";
import { ScenarioAssist } from "@/components/Assist";
import { Callout, Card, Note, Panel, Segmented, Skeleton, cx } from "@/components/ui";
import { MONTHS_SHORT, chf, frDate } from "@/lib/format";
import { PREVISIONS_KEEP, planAction, usePrevisions, type Previsions } from "@/lib/previsions";
import { useView } from "@/lib/url";

import { Independence } from "./previsions/Freedom";
import { Months } from "./previsions/Months";
import { Contributions, SplitLegend, lines, stacked, tipParts, type SplitMode } from "./previsions/Parts";
import { PlanEditor } from "./previsions/Plan";
import { RateSettings } from "./previsions/Rates";
import { Scenarios } from "./previsions/Scenarios";

const KEEP = PREVISIONS_KEEP;

export default function PrevisionsPage() {
  const { data, isPending, isPlaceholderData, error } = usePrevisions();
  if (error) return <Callout tone="bad" title="Les prévisions n'ont pas pu être chargées">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-64 rounded-card" /></div>;
  if (data.empty) return <Callout title="Aucun relevé">Les prévisions partent du solde du relevé.</Callout>;
  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <Body d={data} />
    </div>
  );
}

function shortMonth(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
}

function Body({ d }: { d: Previsions }) {
  const p = d.projection;
  return (
    <>
      <PageHeader
        title="Prévisions"
        subtitle={<>{d.horizon_label} à partir du solde au {frDate(d.as_of)} · une estimation, pas un relevé</>}
      />
      <div className="space-y-4 sm:space-y-5">
        <Scenarios d={d} />
        <ScenarioAssist months={d.months} />
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {[
            { label: "Cash aujourd'hui", value: p.cash, note: `solde CHF au ${frDate(d.as_of)}` },
            { label: "Revenu mensuel", value: p.income, note: d.plan.income != null ? "déclaré dans le plan" : "médiane de l'historique" },
            { label: "Dépense de base", value: p.baseline, note: d.plan.spend != null ? `déclarée · l'historique dit ${chf(p.baseline_history, 0)}` : "hors ponctuels, pics saisonniers retirés" },
            { label: "Solde le plus bas", value: p.low.amount, note: p.low.key ? `en ${p.low.label}` : "aujourd'hui", tone: p.low.amount < 0 ? "text-critical" : "" },
          ].map((k) => (
            <Card key={k.label} className="p-4 sm:p-5">
              <div className="eyebrow truncate">{k.label}</div>
              <div className={cx("mt-1.5 flex items-baseline gap-1.5 text-[24px] font-semibold leading-none tracking-[-0.03em] sm:text-[26px]", k.tone)}>
                <Num value={k.value} className="num" /><span className="text-[12px] font-medium tracking-normal text-muted">CHF</span>
              </div>
              <div className="mt-1.5 text-[12px] text-muted">{k.note}</div>
            </Card>
          ))}
        </div>
        <Projection d={d} />
        {d.wealth && <Wealth d={d} />}
        {d.wealth && <Contributions d={d} />}
        {d.freedom && <Independence f={d.freedom} />}
        <Panel id="p-rates" foldable defaultOpen={false} title="Rendement et volatilité supposés"
               hint="un taux par année, au centième ; un barème par poche ; la largeur de la zone ; les scénarios de marché">
          <RateSettings d={d} />
        </Panel>
        <Months d={d} />
        {d.profile.length > 0 && <Profile d={d} />}
        <PlanEditor d={d} />
      </div>
    </>
  );
}

/* ------------------------------------------------------------ projection */

function Projection({ d }: { d: Previsions }) {
  const p = d.projection;
  const labels = ["aujourd'hui", ...p.rows.map((r) => r.label)];
  const values = [p.cash, ...p.rows.map((r) => r.end)];
  const lowIndex = values.indexOf(Math.min(...values));
  const refs = [
    ...(Math.min(...values) < 0 ? [{ value: 0, color: "var(--critical)", label: "0" }] : []),
    ...(d.floor != null ? [{ value: d.floor, color: "var(--warn)", label: `seuil ${chf(d.floor, 0)}`, dash: true }] : []),
  ];
  return (
    <Panel id="p-cash" title="Solde projeté" hint="pointillé = prévu · chaque point est la fin d'un mois"
           actions={<FloorField d={d} />}>
      <Lines xs={values.map((_, i) => i)} height={230} zero={false}
             series={[{ key: "cash", name: "Solde", color: "var(--s0)", values, dash: true, area: true }]}
             markers={[{ index: lowIndex, series: "cash", label: `bas ${chf(values[lowIndex], 0)}` }]}
             refs={refs}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             tipExtra={(i) => {
               if (i === 0) return [];
               const r = p.rows[i - 1];
               return [
                 { name: "Revenus", value: `+${chf(r.income, 0)}` },
                 { name: "Dépenses", value: `−${chf(r.spend, 0)}` },
                 ...r.one_offs.map((o) => ({ name: o.label, value: `−${chf(o.amount, 0)}` })),
               ];
             }}
             xLabel={(i) => labels[i]}
             xTicks={(w) => spreadTicks(values.length, w, (i) => (i === 0 ? "auj." : shortMonth(p.rows[i - 1].key)), 64)}
             ariaLabel="Évolution prévue du solde mois par mois" />
      {d.floor_alert?.below && (
        <Callout tone="warn" className="mt-3" title="Sous ton seuil">
          {d.floor_alert.text} {d.floor_alert.count! > 1 ? `${d.floor_alert.count} fins de mois sur ${d.floor_alert.months} en dessous.` : ""} Le résumé de la semaine et la barre latérale le rappellent tant que le plan affiché y passe.
        </Callout>
      )}
      {d.floor_alert && !d.floor_alert.below && (
        <p className="mt-3 text-[12.5px] text-good">Le plan tient : jamais sous {chf(d.floor_alert.floor, 0)} CHF sur {d.horizon_label}.</p>
      )}
      <Note>Cash initial + revenus mensuels − dépense de base − ponctuels. Les montants sont des médianes du passé ; la seule certitude est le solde du relevé.</Note>
    </Panel>
  );
}

/** The cash not to go under: typed once, then the line on the chart, the
 * callout under it, and the alert on every page and in the weekly summary. */
function FloorField({ d }: { d: Previsions }) {
  const [text, setText] = useState(d.floor != null ? chf(d.floor, 0) : "");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setText(d.floor != null ? chf(d.floor, 0) : ""); }, [d.floor]);
  const save = async (e?: FormEvent) => {
    e?.preventDefault();
    const typed = text.trim();
    if ((d.floor == null && !typed) || (d.floor != null && typed === chf(d.floor, 0))) return;
    const r = await planAction(d.months, { action: "floor", amount: typed });
    if (r.errors) { setError(Object.values(r.errors)[0]); return; }
    setError(null);
    toast.success(typed ? `Seuil d'alerte : ${typed} CHF` : "Seuil d'alerte retiré");
  };
  return (
    <form onSubmit={save} className="flex items-center gap-2">
      <label htmlFor="cash-floor" className="whitespace-nowrap text-[12.5px] text-muted">Seuil d'alerte</label>
      <Input id="cash-floor" value={text} inputMode="numeric" placeholder="aucun" invalid={!!error}
             title={error ?? "Le cash à ne pas passer : laissé vide, pas d'alerte"} aria-describedby={error ? "cash-floor-error" : undefined}
             className="!h-9 !w-28 text-right sm:!h-8 sm:!text-[13px]" onChange={(e) => { setText(e.target.value); setError(null); }} onBlur={() => void save()} />
      {error && <span id="cash-floor-error" role="alert" className="text-[12px] text-critical">{error}</span>}
    </form>
  );
}

/* ---------------------------------------------------------------- wealth */

const SPLITS: { id: SplitMode; label: string }[] = [
  { id: "total", label: "Total" }, { id: "pockets", label: "Par poche" }, { id: "classes", label: "Par classe" },
];

function Wealth({ d }: { d: Previsions }) {
  const { href, params } = useView();
  const mode = (SPLITS.find((s) => s.id === params.get("split"))?.id ?? "total") as SplitMode;
  const w = d.wealth!;
  const obs = w.observed;
  const n = obs.length;
  const total = n + w.rows.length;
  const xs = Array.from({ length: total }, (_, i) => i);
  const observed = xs.map((i) => (i < n ? obs[i].total : null));
  const projected = xs.map((i) => (i === n - 1 ? obs[n - 1].total : i >= n ? w.rows[i - n].total : null));
  const band = w.vol ? {
    low: xs.map((i) => (i === n - 1 ? obs[n - 1].total : i >= n ? w.rows[i - n].low : null)),
    high: xs.map((i) => (i === n - 1 ? obs[n - 1].total : i >= n ? w.rows[i - n].high : null)),
    color: "var(--s1)",
  } : undefined;
  const labelAt = (i: number) => (i < n ? obs[i].label : w.rows[i - n].label);
  const view = d.wealth_views.find((v) => v.id === d.wealth_view);
  const values = [...observed, ...projected, ...(band?.low ?? [])].filter((v): v is number => v != null);
  const logBlocked = d.yscale === "log" && values.some((v) => v <= 0);
  const split = mode === "pockets" ? w.parts.pockets : mode === "classes" ? w.parts.classes : null;
  const stack = split ? stacked(split, n) : null;
  const layers = { stacked: !!stack, series: split ? stack ?? lines(split, n) : [] };
  return (
    <Panel title="Patrimoine"
           hint={<>trait plein = mesuré · pointillé = projeté{w.vol && mode === "total" ? " · la zone est ±1 écart-type" : ""}{logBlocked && " · échelle linéaire : le log exige des valeurs positives"}</>}
           actions={<>
             <Segmented size="sm" label="Portée fiscale" value={d.wealth_view}
                        options={d.wealth_views.map((v) => ({ id: v.id, label: v.label, title: v.note }))}
                        hrefFor={(id) => href({ wealth: id === "all" ? null : id }, { keep: KEEP })} />
             <Segmented size="sm" label="Échelle" value={d.yscale} options={d.yscales}
                        hrefFor={(id) => href({ yscale: id === "linear" ? null : id }, { keep: KEEP })} />
             <Segmented size="sm" label="Répartition" value={mode} options={SPLITS}
                        hrefFor={(id) => href({ split: id === "total" ? null : id }, { keep: KEEP })} />
           </>}>
      <p className="mb-3 rounded-xl bg-surface-2/60 px-3 py-2 text-[13px] text-ink-2">
        <b className="text-ink">{view?.note}</b>
        {d.wealth_view === "sheltered" && " · le 3a sort de la fortune imposable jusqu'au retrait."}
        {d.wealth_view === "taxable" && " · l'assiette de l'impôt cantonal sur la fortune."}
      </p>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div><div className="eyebrow">Aujourd'hui</div><div className="num mt-1 text-[18px] font-semibold">{chf(obs[n - 1].total, 0)}</div></div>
        <div><div className="eyebrow">Dans {d.horizon_label}</div><div className="num mt-1 text-[18px] font-semibold">{chf(w.final.total, 0)}</div></div>
        {w.vol > 0 && <div className="col-span-2 sm:col-span-1"><div className="eyebrow">À ±1 écart-type</div>
          <div className="num mt-1 text-[14px] font-medium text-ink-2">{chf(w.final.low, 0)} – {chf(w.final.high, 0)}</div></div>}
      </div>
      {split ? (
        <Lines xs={xs} height={280} zero={!layers.stacked ? d.scale === "zero" : true} yLog={!layers.stacked && d.yscale === "log"}
               series={[...layers.series,
                 { key: "seen", name: "Total mesuré", color: "var(--ink)", values: observed, width: 1.5 },
                 { key: "proj", name: "Total projeté", color: "var(--ink)", values: projected, dash: true, width: 1.5 }]}
               todayIndex={n - 1}
               tipFormat={(v) => `${chf(v, 0)} CHF`}
               tipExtra={(i) => tipParts(split, n, i)}
               xLabel={labelAt}
               xTicks={(wd) => spreadTicks(total, wd, (i) => (i < n ? obs[i].label : shortMonth(w.rows[i - n].key)), 70)}
               ariaLabel={`${view?.title} ${mode === "pockets" ? "par poche" : "par classe d'actifs"}, ${n} mois observés puis ${w.rows.length} mois projetés`} />
      ) : (
      <Lines xs={xs} height={260} zero={d.scale === "zero"} yLog={d.yscale === "log"}
             series={[
               { key: "seen", name: "Mesuré", color: "var(--s1)", values: observed, area: false },
               { key: "proj", name: "Projeté", color: "var(--s1)", values: projected, dash: true },
             ]}
             band={band} todayIndex={n - 1}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             tipExtra={(i) => (i >= n && w.vol ? [{ name: "±1σ", value: `${chf(w.rows[i - n].low, 0)} – ${chf(w.rows[i - n].high, 0)}` }] : [])}
             xLabel={labelAt}
             xTicks={(wd) => spreadTicks(total, wd, (i) => (i < n ? obs[i].label : shortMonth(w.rows[i - n].key)), 70)}
             ariaLabel={`${view?.title}, ${n} mois observés puis ${w.rows.length} mois projetés`} />
      )}
      {split && <SplitLegend sp={split} horizon={d.horizon_label} />}
      {split && !layers.stacked && <p className="mt-1 text-[12px] text-muted">Une part passe sous zéro : les parts sont dessinées en lignes, pas empilées.</p>}
      <Note>
        La moitié gauche est mesurée ; la droite ajoute la projection de trésorerie aux placements
        {w.rated ? " capitalisés selon votre barème — votre hypothèse, pas celle de l'app." : ", figés à leur dernière valeur : aucun rendement n'est supposé tant que vous n'en déclarez pas."}
        {w.vol > 0 && ` La zone est ±1 écart-type, ${(w.vol * 100).toFixed(1)} % annualisés ${w.vol_source === "declared" ? "déclarés" : "mesurés sur vos poches"}, élargi en √t.`}
        {w.moved ? ` ${chf(w.moved, 0)} CHF de virements déclarés sortent de la trésorerie sans quitter le patrimoine.` : ""}
      </Note>
    </Panel>
  );
}

/* --------------------------------------------------------------- profile */

function Profile({ d }: { d: Previsions }) {
  return (
    <Panel foldable defaultOpen={false} title="Analyse mensuelle" hint="la médiane des mois observés ; la part claire est le pic saisonnier retiré de la base">
      <MonthlyProfile profile={d.profile} baseline={d.projection.baseline} />
      <Note>Chaque barre est la médiane des mois observés de ce mois calendaire ; la part claire est ce que les factures annuelles détectées retirent, la même soustraction que la dépense de base. Le pointillé est cette base.</Note>
    </Panel>
  );
}
