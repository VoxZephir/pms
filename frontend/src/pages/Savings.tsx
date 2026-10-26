/** The savings: the money outside the spending, every pocket. Read top
 * down -- what it is worth and why it moved, how it evolved, what it is made
 * of, how each pocket did -- and, folded, the figures for whoever wants them:
 * the target allocation, the coins, the fees, the tax return, the risk. */
import { Download, SlidersHorizontal } from "lucide-react";
import { Popover } from "radix-ui";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Lines, monthTicks } from "@/charts/Lines";
import { SavingsAssist } from "@/components/Assist";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageState";
import { FetchButton } from "./savings/Fetch";
import { Sheet } from "@/components/Sheet";
import { Table } from "@/components/Table";
import { Button, Callout, Card, Chip, Dot, Note, Panel, Segmented, Skeleton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, day, frDate, signedChf, signedRate } from "@/lib/format";
import { useDesktop } from "@/lib/hooks";
import type { PocketRow, Savings } from "@/lib/savings";
import { useView } from "@/lib/url";
import { Falls, MonthGrid, PocketCards, WhereFrom } from "./savings/Reads";

const PART_COLORS = ["var(--s0)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)"];

function tone(v: number | null | undefined, eps = 0.0005) {
  if (v == null) return "";
  return v >= eps ? "text-good" : v <= -eps ? "text-critical" : "";
}

function pts(v: number | null | undefined) {
  if (v == null) return "—";
  if (Math.abs(v) < 0.0005) return "0.0 pts";
  return `${v > 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} pts`;
}

export default function SavingsPage() {
  const { query } = useView();
  const { data, isPending, isPlaceholderData, error } = useApi<Savings>("/api/savings", query);
  if (error) return <Callout tone="bad" title="L'épargne n'a pas pu être chargée">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-48" /><Skeleton className="h-56 rounded-card" /><Skeleton className="h-72 rounded-card" /></div>;
  if (data.empty || !data.available) {
    return (
      <>
        <PageHeader title="Épargne" />
        <Callout title="Aucune donnée d'épargne">
          Le panneau lit <code>data/ibkr.json</code> : en session Claude Code, <code>/epargne</code> le capture.
        </Callout>
      </>
    );
  }
  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <SavingsBody s={data} />
    </div>
  );
}

function SavingsBody({ s }: { s: Savings }) {
  return (
    <>
      <PageHeader
        title="Épargne"
        subtitle={<>au {frDate(s.period.end)} · {s.period.title}
          {s.focus !== "total" && <> · {s.options.focuses.find((f) => f.id === s.focus)?.label}</>}</>}
        actions={<div className="flex flex-wrap items-center gap-2">
          {s.titres.declared > 0 && <TitresSwitch s={s} />}
          <FetchButton />
        </div>}
      />
      <div className="space-y-4 sm:space-y-5">
        {s.stale.length > 0 && (
          <Callout tone="warn" title="Données en retard">
            {s.stale.join(" · ")}. « Rafraîchir », en haut de la page, les va chercher ; sinon, en session Claude Code : <code>/epargne</code>.
          </Callout>
        )}
        <Hero s={s} />
        <PocketCards s={s} />
        <SavingsAssist />
        {s.evolution.rows.length > 1 && <Evolution s={s} />}
        <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
          <WhereFrom s={s} />
          <Composition s={s} />
        </div>
        {s.invested && s.invested.rows.length > 1 && <Invested s={s} />}
        <MonthGrid s={s} />
        <Falls s={s} />
        <Notes s={s} />
        <Pockets s={s} />
        <Allocation s={s} />
        {s.crypto && s.crypto.positions.length > 0 && <Crypto s={s} />}
        <Fees s={s} />
        {s.tax && s.tax.years.length > 0 && <Tax s={s} />}
        {s.risk && <Risk s={s} />}
        <Note className="px-1">
          <b>Sources.</b> Swissquote : le relevé, ligne par ligne. IBKR{s.opened ? ` (ouvert le ${frDate(s.opened)})` : ""} :{" "}
          {s.reconstructed_until && `valeur reconstruite chaque semaine jusqu'au ${frDate(s.reconstructed_until)}, puis `}
          valeur quotidienne du courtier, capturée le {frDate(s.captured_on ?? s.captured_at ?? "")}.
          {s.finpension && ` 3a : ${chf(s.finpension.value, 0)} CHF relevés le ${frDate(s.finp_as_of ?? s.finpension.value_as_of)}, estimés depuis par des indices de référence ; ${chf(s.finpension.deposits, 0)} CHF versés en tout.`}
          {" "}L'app ne lit jamais les comptes en direct : <code>/epargne</code> les met à jour.
        </Note>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ hero */

function Hero({ s }: { s: Savings }) {
  const { href } = useView();
  const h = s.hero;
  const mwr = s.perf === "mwr";
  const perYear = s.rate === "annual";
  const rate = mwr ? h.mwr : h.twr;
  const pa = mwr ? h.mwr_pa : h.twr_pa;
  const annual = mwr ? h.mwr_annual : h.twr_annual;
  const yearly = perYear && pa != null;
  const timing = yearly ? h.timing_pa : h.timing;
  const shown = yearly ? pa : rate;

  return (
    <Card className="overflow-hidden">
      <div className="grid divide-y divide-hairline md:grid-cols-3 md:divide-x md:divide-y-0">
        <div className="p-5 sm:p-6">
          <div className="eyebrow">{h.name}</div>
          <div className="mt-2 flex items-baseline gap-1.5 text-[34px] font-semibold leading-none tracking-[-0.035em] sm:text-[40px]">
            <Num value={h.value} className="num" /><span className="text-[13px] font-medium tracking-normal text-muted">CHF</span>
          </div>
          <div className="mt-2 text-[12.5px] text-muted">au {frDate(s.period.end)}</div>
        </div>
        <div className="p-5 sm:p-6">
          <div className="eyebrow">Sur la période</div>
          <div className={cx("mt-2 flex items-baseline gap-1.5 text-[28px] font-semibold leading-none tracking-[-0.03em] sm:text-[32px]", tone(h.change, 0.5))}>
            <Num value={h.change} format={(v) => signedChf(v)} className="num" /><span className="text-[13px] font-medium tracking-normal text-muted">CHF</span>
          </div>
          <div className="mt-2.5 space-y-1 text-[13px] text-ink-2">
            <div className="flex justify-between gap-3">
              <span>{h.pocket === "total" ? "Mis de côté" : h.pocket === "swissquote" ? "Entrées nettes" : "Versé"}</span>
              <b className="num">{signedChf(h.put_in)}</b>
            </div>
            <div className="flex justify-between gap-3">
              <span>{h.pocket === "swissquote" ? "Intérêts" : "Rendement"}</span>
              <b className={cx("num", tone(h.gain, 0.5))}>{signedChf(h.gain)}</b>
            </div>
          </div>
        </div>
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow">Performance</span>
            <Segmented size="sm" label="Mesure" value={s.perf} options={s.options.perfs}
                       hrefFor={(id) => href({ perf: id === "twr" ? null : id })} />
            <Segmented size="sm" label="Sur la période ou par an" value={s.rate} options={s.options.rates}
                       hrefFor={(id) => href({ rate: id === "period" ? null : id })} />
          </div>
          {h.pocket === "swissquote" ? (
            <>
              <div className="mt-2 text-[32px] font-semibold leading-none">—</div>
              <p className="mt-2 text-[12.5px] text-muted">Un compte courant n'a pas de rendement à mesurer : son solde suit les entrées et les dépenses.</p>
            </>
          ) : (
            <>
              <div className={cx("mt-2 flex items-baseline gap-1.5 text-[32px] font-semibold leading-none tracking-[-0.03em]", tone(shown))}>
                <span className="num">{signedRate(shown)}</span>
                {yearly && <span className="text-[13px] font-medium tracking-normal text-muted">par an</span>}
              </div>
              <p className="mt-2 text-[12.5px] text-muted">
                {mwr ? "l'argent placé, chaque versement pondéré par sa durée" : "les placements, versements retirés"}
                {yearly ? ` · ${signedRate(rate)} sur la période`
                  : perYear ? " · moins d'un an : rendement sur la période, non extrapolé"
                  : annual != null ? ` · ${signedRate(annual)} par an` : ""}
              </p>
              {timing != null && (
                <p className="mt-1 text-[12.5px] text-muted" title="MWR − TWR : positif, les versements sont arrivés avant les hausses">
                  timing des versements <b className={tone(timing)}>{pts(timing)}</b>{yearly ? " par an" : ""}
                  {h.timing_chf != null && ` · ${signedChf(h.timing_chf)} CHF`}
                </p>
              )}
              <Benchmarks s={s} perYear={perYear} />
              {s.attribution && h.pocket === "ibkr" && (
                <p className="mt-1 text-[12.5px] text-muted">
                  dont fonds {s.attribution.fund_name} en USD <b className={tone(s.attribution.fund)}>{signedRate(s.attribution.fund)}</b>
                  {" "}· dollar <b className={tone(s.attribution.fx)}>{signedRate(s.attribution.fx)}</b>
                  {" "}· reste <b className={tone(s.attribution.rest)}>{signedRate(s.attribution.rest)}</b>
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function Benchmarks({ s, perYear }: { s: Savings; perYear: boolean }) {
  return (
    <div className="mt-3 rounded-xl bg-surface-2/60 px-3 py-2 text-[12.5px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-ink-2">Repères, même période{perYear ? ", par an" : ""}</span>
        <BenchPicker s={s} />
      </div>
      {s.bench.length ? (
        <ul className="mt-1 space-y-0.5">
          {s.bench.map((b) => {
            const v = perYear && b.rate_pa != null ? b.rate_pa : b.rate;
            return (
              <li key={b.name} className="flex justify-between gap-3" title={b.source}>
                <span className="truncate text-ink-2">{b.name}{!b.total_return && " *"}{b.since && ` (depuis le ${frDate(b.since)})`}</span>
                <b className={cx("num", tone(v))}>{signedRate(v)}</b>
              </li>
            );
          })}
        </ul>
      ) : <div className="mt-1 text-muted">Aucun repère choisi.</div>}
      {s.bench.some((b) => !b.total_return) && <div className="mt-1 text-[11.5px] text-muted">* prix seul, dividendes non compris</div>}
    </div>
  );
}

function BenchPicker({ s }: { s: Savings }) {
  const { go } = useView();
  const desktop = useDesktop();
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState<Set<string>>(new Set(s.bench_options.filter((o) => o.on && o.available).map((o) => o.key)));
  const apply = () => {
    const keys = s.bench_options.filter((o) => on.has(o.key)).map((o) => o.key);
    go({ bench: keys.length ? keys.join(",") : "none" });
    setOpen(false);
  };
  const body = (
    <div className="space-y-1">
      {s.bench_options.map((o) => (
        <label key={o.key} title={o.available ? o.source : "pas encore capturé : python -m pms --benchmarks"}
               className={cx("flex items-center gap-3 rounded-lg px-2 py-2 text-[14px]", o.available ? "hover:bg-surface-2" : "opacity-45")}>
          <input type="checkbox" disabled={!o.available} checked={on.has(o.key)} className="size-4 accent-[var(--ink)]"
                 onChange={(e) => setOn((cur) => { const n = new Set(cur); if (e.target.checked) n.add(o.key); else n.delete(o.key); return n; })} />
          {o.name}
        </label>
      ))}
      <p className="px-2 pt-1 text-[12px] text-muted">Dividendes réinvestis ; tracés en pointillés sur la courbe, en base 100.</p>
      <Button variant="primary" className="mt-2 w-full" onClick={apply}>Comparer</Button>
    </div>
  );
  const trigger = (
    <button type="button" className="inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[12px] font-medium text-accent hover:bg-surface"
            onClick={desktop ? undefined : () => setOpen(true)}>
      <SlidersHorizontal size={12} /> Choisir
    </button>
  );
  if (!desktop) {
    return <>{trigger}<Sheet open={open} onOpenChange={setOpen} title="Repères">{body}</Sheet></>;
  }
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>{trigger}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} align="end" className="z-50 w-72 rounded-2xl border border-hairline bg-surface p-3 shadow-pop">{body}</Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/* ------------------------------------------------------------- evolution */

function Evolution({ s }: { s: Savings }) {
  const { href } = useView();
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [stack, setStack] = useState(false);
  const ev = s.evolution;
  const xs = useMemo(() => ev.rows.map((r) => day(String(r.date)).getTime()), [ev.rows]);
  const index = s.scale === "index";
  const shown = ev.spec.filter((sp) => !hidden.has(sp.key));
  const raw = (key: string) => ev.rows.map((r) => (r[key] == null ? null : Number(r[key])));
  // Stacking needs parts that add up to something: amounts, more than one
  // part, none below zero. The total line is what the stack's top draws.
  const parts = shown.filter((sp) => sp.key !== "total" && !sp.dash);
  const canStack = !index && parts.length > 1 && parts.every((sp) => raw(sp.key).every((v) => v == null || v >= -0.5));
  const stacked = stack && canStack;
  let series;
  if (stacked) {
    let below = ev.rows.map(() => 0);
    series = parts.map((sp) => {
      const top = raw(sp.key).map((v, i) => below[i] + (v ?? 0));
      const out = { key: sp.key, name: sp.name, color: `var(--s${sp.slot})`, values: top, fillTo: below, silent: true, width: 1.25 };
      below = top;
      return out;
    });
  } else {
    series = shown.map((sp) => ({
      key: sp.key, name: sp.name, color: `var(--s${sp.slot})`, dash: sp.dash,
      width: sp.key === "total" ? 2.5 : sp.dash ? 1.5 : 2,
      values: raw(sp.key),
    }));
  }
  const tipStack = (i: number) => [...parts].reverse().map((sp) => ({
    name: sp.name, color: `var(--s${sp.slot})`, value: `${chf(Number(ev.rows[i][sp.key] ?? 0), 0)} CHF`,
  })).concat(ev.spec.some((sp) => sp.key === "total") ? [{ name: "Épargne totale", color: "var(--s1)", value: `${chf(Number(ev.rows[i].total ?? 0), 0)} CHF` }] : []);
  return (
    <Panel id="p-evolution" title="Évolution"
           hint={index ? (s.perf === "mwr" ? "base 100 au premier point · MWR, versements pondérés à leur date" : "base 100 au premier point · TWR, versements retirés")
             : stacked ? "en francs, empilé : chaque bande est une poche, le haut est le total"
             : "en francs · la mesure TWR / MWR s'applique en base 100"}
           actions={<div className="flex flex-wrap items-center gap-2">
             {canStack && <Segmented size="sm" label="Lignes ou bandes" value={stacked ? "stack" : "lines"} onChange={(id) => setStack(id === "stack")}
                                     options={[{ id: "lines", label: "Lignes" }, { id: "stack", label: "Empilé" }]} />}
             <Segmented size="sm" label="Lecture de la courbe" value={s.scale} options={s.options.scales}
                        hrefFor={(id) => href({ scale: id === "zero" ? null : id })} />
           </div>}>
      <Lines xs={xs} series={series} height={260} zero={s.scale === "zero"}
             format={index ? (v) => v.toFixed(0) : undefined}
             tipFormat={(v) => (index ? v.toFixed(1) : `${chf(v, 0)} CHF`)}
             tipExtra={stacked ? tipStack : undefined}
             xLabel={(i) => frDate(String(ev.rows[i].date))}
             xTicks={(w) => monthTicks(xs, w, 64)}
             refs={index ? [{ value: 100, color: "var(--axis)", dash: true }] : []}
             ariaLabel="Évolution de l'épargne sur la période" />
      <div className="mt-3 flex flex-wrap gap-2">
        {ev.spec.map((sp) => {
          const off = hidden.has(sp.key);
          return (
            <button key={sp.key} type="button" aria-pressed={!off}
                    onClick={() => setHidden((h) => { const n = new Set(h); if (off) n.delete(sp.key); else n.add(sp.key); return n; })}
                    className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] transition",
                      off ? "border-hairline text-muted line-through" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
              {sp.dash ? <i className="h-0 w-3 border-t-2 border-dashed" style={{ borderColor: `var(--s${sp.slot})` }} /> : <Dot color={`var(--s${sp.slot})`} />}
              {sp.name}
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

/* ----------------------------------------------------- contributions vs value */

const POCKET_NAMES: Record<string, string> = { ibkr: "IBKR", finpension: "3a", crypto: "crypto", titres: "titres" };

/** What went in, and what it is worth: the money put into the invested
 * pockets since they opened, a step at each deposit, under the value; the
 * area between is the gain (or the loss). Computed by the savings book,
 * the same that feeds the rest of the page. */
function Invested({ s }: { s: Savings }) {
  const iv = s.invested!;
  const xs = useMemo(() => iv.rows.map((r) => day(r.date).getTime()), [iv.rows]);
  const up = iv.gain >= 0;
  return (
    <Panel title="Versements et valeur"
           hint={`${iv.pockets.map((p) => POCKET_NAMES[p] ?? p).join(" + ")} · versements cumulés depuis l'ouverture, face à ce qu'ils valent`}>
      <div className="mb-3 grid grid-cols-3 gap-3">
        <div><div className="eyebrow">Versé</div><div className="num mt-1 text-[18px] font-semibold">{chf(iv.contributed, 0)}</div></div>
        <div><div className="eyebrow">Valeur</div><div className="num mt-1 text-[18px] font-semibold">{chf(iv.value, 0)}</div></div>
        <div><div className="eyebrow">{up ? "Plus-value" : "Moins-value"}</div>
          <div className={cx("num mt-1 text-[18px] font-semibold", up ? "text-good" : "text-critical")}>
            {up ? "+" : "−"}{chf(Math.abs(iv.gain), 0)}
            {iv.gain_pct != null && <span className="ml-1 text-[12.5px] font-medium">({up ? "+" : ""}{iv.gain_pct.toFixed(1)} %)</span>}
          </div></div>
      </div>
      <Lines xs={xs} height={240} zero={false}
             series={[
               { key: "value", name: "Valeur", color: "var(--s0)", values: iv.rows.map((r) => r.value), area: true, width: 2.5 },
               { key: "contributed", name: "Versé (cumul)", color: "var(--ink-2)", values: iv.rows.map((r) => r.contributed), step: true, dash: true, width: 1.75 },
             ]}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             tipExtra={(i) => {
               const r = iv.rows[i];
               const g = r.value - r.contributed;
               return [{ name: g >= 0 ? "Plus-value" : "Moins-value", value: `${g >= 0 ? "+" : "−"}${chf(Math.abs(g), 0)}` }];
             }}
             xLabel={(i) => frDate(iv.rows[i].date)}
             xTicks={(w) => monthTicks(xs, w, 64)}
             ariaLabel="Versements cumulés et valeur du portefeuille" />
      <div className="mt-2 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><Dot color="var(--s0)" />Valeur</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-0 w-3 border-t-2 border-dashed border-ink-2" />Versé (cumul)</span>
      </div>
      <Note>Un versement monte la marche ; l'écart entre les deux courbes est ce que les marchés ont ajouté ou retiré. Un virement Swissquote → IBKR compte comme versement, un dépôt 3a aussi ; l'ouverture d'IBKR compte comme son premier versement.</Note>
    </Panel>
  );
}

/* ----------------------------------------------------------- composition */

function Composition({ s }: { s: Savings }) {
  const { href } = useView();
  const total = s.parts.reduce((a, p) => a + p.value, 0) || 1;
  const ex = s.allocation.exposure;
  const levered = s.positions.filter((p) => p.exposure > 1);
  return (
    <Panel title="Composition" actions={
      <Segmented size="sm" label="Répartition" value={s.split} options={s.options.splits}
                 hrefFor={(id) => href({ split: id === "account" ? null : id })} />
    }>
      <div className="flex h-10 w-full gap-[3px] overflow-hidden rounded-xl" role="img" aria-label="Répartition de l'épargne">
        {s.parts.map((p, i) => (
          <div key={p.name} title={`${p.name} : ${chf(p.value, 0)} CHF · ${((p.value / total) * 100).toFixed(1)} %`}
               className="h-full min-w-[3px] transition-[width] duration-500 first:rounded-l-xl last:rounded-r-xl"
               style={{ width: `${(p.value / total) * 100}%`, background: PART_COLORS[i % PART_COLORS.length] }} />
        ))}
      </div>
      <ul className="mt-4 space-y-1.5">
        {s.parts.map((p, i) => (
          <li key={p.name} className="grid grid-cols-[auto_1fr_auto_56px] items-center gap-3 text-[14px]">
            <Dot color={PART_COLORS[i % PART_COLORS.length]} />
            <span className="truncate">{p.name}</span>
            <b className="num">{chf(p.value, 0)}</b>
            <span className="num text-right text-[12.5px] text-muted">{((p.value / total) * 100).toFixed(1)} %</span>
          </li>
        ))}
      </ul>
      {ex && s.focus === "total" && s.split === "asset" && levered.length > 0 && (
        <Note>
          En francs. En exposition{levered.map((p) => `, ${p.name} compte ×${p.exposure.toFixed(1)}`).join("")} :{" "}
          {ex.rows.filter((r) => r.name !== "Cash").map((r) => `${r.name} ${Math.round(r.share)} %`).join(", ")} de la fortune,
          {" "}{Math.round(ex.gross)} % au total.
        </Note>
      )}
    </Panel>
  );
}

function Notes({ s }: { s: Savings }) {
  const rv = s.reserve;
  const p3 = s.pillar3a;
  if (!rv && !p3) return null;
  return (
    <div className="grid gap-4 sm:gap-5 md:grid-cols-2">
      {rv && (
        <Card className="p-5">
          <div className="eyebrow">Réserve</div>
          <div className="mt-1.5 text-[24px] font-semibold tracking-tight"><span className="num">{rv.months.toFixed(1)}</span> <span className="text-[14px] font-medium text-muted">mois de besoins</span></div>
          <p className="mt-1.5 text-[13px] text-ink-2">
            {chf(rv.monthly, 0)} CHF par mois en moyenne sur {rv.basis} mois, impôts et primes compris ; repère usuel {rv.low} à {rv.high} mois.
            {rv.excess > 0 ? <> Au-delà de {rv.high} mois, <b>{chf(rv.excess, 0)} CHF</b> ne rapportent rien.</>
              : rv.short > 0 ? <> Il manque <b>{chf(rv.short, 0)} CHF</b> pour atteindre {rv.low} mois.</> : null}
          </p>
        </Card>
      )}
      {p3 && (
        <Card className="p-5">
          <div className="eyebrow">3a {p3.year}</div>
          <div className="mt-1.5 text-[24px] font-semibold tracking-tight">
            <span className="num">{chf(p3.paid, 0)}</span> <span className="text-[14px] font-medium text-muted">/ {chf(p3.ceiling, 0)} CHF</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-s2" style={{ width: `${Math.min(100, (p3.paid / p3.ceiling) * 100)}%` }} />
          </div>
          <p className="mt-2 text-[13px] text-ink-2">
            {p3.left > 0 && p3.days_left != null
              ? <>Reste <b>{chf(p3.left, 0)} CHF</b> déductibles, à créditer avant le 31.12 ({p3.days_left} jours).</>
              : p3.left > 0 ? <>{chf(p3.left, 0)} CHF non versés.</> : "Plafond atteint."}
            {!p3.published && ` Plafond ${p3.year} pas encore dans l'app : celui de ${p3.year - 1}.`}
            {p3.gaps.map((g) => ` Lacune ${g.year} : ${chf(g.amount, 0)} CHF, rachetable dans les dix ans.`).join("")}
          </p>
        </Card>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- pockets */

function Pockets({ s }: { s: Savings }) {
  const { href } = useView();
  const perYear = s.rate === "annual";
  const rateCell = (period: number | null, yearly: number | null) => {
    const v = perYear && yearly != null ? yearly : period;
    return <span className={tone(v)} title={perYear && yearly == null && period != null ? "moins d'un an : rendement sur la période, non extrapolé" : undefined}>
      {signedRate(v)}{perYear && yearly == null && period != null ? "*" : ""}</span>;
  };
  return (
    <Panel id="p-pockets" foldable defaultOpen={false} title="Par poche, en détail"
           hint={`apports, rendement, contribution, TWR, MWR, timing et frais ${perYear ? "par an" : "sur la période"}`}>
      <Table<PocketRow>
        rows={s.pockets} rowKey={(r) => r.pocket} sortable={false}
        rowClass={(r) => cx(r.pocket === "total" && "font-semibold", r.pocket === s.focus && "bg-surface-2/60")}
        cols={[
          { key: "name", label: "Poche", render: (r) => (
            <Link to={href({ focus: r.pocket === "total" ? null : r.pocket })} preventScrollReset className="underline-offset-2 hover:underline">
              {r.name}{r.pocket === "finpension" && <Chip className="ml-2">estimé</Chip>}
            </Link>) },
          { key: "value", label: "Valeur", numeric: true, render: (r) => chf(r.value, 0) },
          { key: "share", label: "Part", numeric: true, render: (r) => (r.share != null ? `${r.share.toFixed(1)} %` : "—"), wide: true },
          { key: "put_in", label: "Apports nets", numeric: true, render: (r) => signedChf(r.put_in) },
          { key: "gain", label: "Rendement", numeric: true, render: (r) => <span className={tone(r.gain, 0.5)}>{signedChf(r.gain)}</span> },
          { key: "contribution", label: "Contribution", numeric: true, wide: true, title: "contribution à la performance du total (Dietz modifié)",
            render: (r) => <span className={tone(r.contribution)}>{pts(r.contribution)}</span> },
          { key: "twr", label: "TWR", numeric: true, render: (r) => rateCell(r.twr, r.twr_pa) },
          { key: "mwr", label: "MWR", numeric: true, render: (r) => rateCell(r.mwr, r.mwr_pa) },
          { key: "timing", label: "Timing", numeric: true, wide: true, render: (r) => {
            const t = perYear && r.timing_pa != null ? r.timing_pa : r.timing;
            return <span className={tone(t)} title={r.timing_chf != null ? `${signedChf(r.timing_chf)} CHF sur la période` : undefined}>{pts(t)}</span>;
          } },
          { key: "fees", label: "Frais", numeric: true, render: (r) => (r.fees ? <span title={r.fees.detail}>{chf(r.fees.amount)}</span> : "—") },
        ]} />
    </Panel>
  );
}

/* ------------------------------------------------------------ allocation */

function Allocation({ s }: { s: Savings }) {
  const al = s.allocation;
  const dr = al.drift;
  const [editing, setEditing] = useState(false);
  const summary = dr && (dr.buy.length || dr.sell.length)
    ? (() => {
      const big = [...dr.rows].sort((a, b) => a.gap - b.gap)[0];
      return `${big.name} ${Math.round(big.share)} % pour ${Math.round(big.target)} % visés`;
    })()
    : dr ? "à la cible" : "aucune cible déclarée";
  return (
    <Panel foldable defaultOpen={false} title="Allocation cible" hint={summary}
           actions={<Button size="sm" onClick={() => setEditing(true)}>{Object.keys(al.targets).length ? "Modifier" : "Déclarer"}</Button>}>
      {dr ? (
        <>
          <Table rows={dr.rows} rowKey={(r) => r.name} sortable={false}
                 cols={[
                   { key: "name", label: "Classe", render: (r) => r.name },
                   { key: "value", label: "Valeur", numeric: true, render: (r) => chf(r.value, 0) },
                   { key: "share", label: "Part", numeric: true, render: (r) => `${r.share.toFixed(1)} %` },
                   ...(al.exposure ? [{ key: "exp", label: "Exposition", numeric: true, wide: true,
                     render: (r: { name: string }) => `${(al.exposure!.by_name[r.name]?.share ?? 0).toFixed(1)} %` }] : []),
                   { key: "target", label: "Cible", numeric: true, render: (r) => `${r.target.toFixed(1)} %` },
                   { key: "gap", label: "Écart", numeric: true, render: (r) => <span className={tone(r.gap, 0.5)}>{signedChf(r.gap)}</span> },
                 ]} />
          {(dr.buy.length > 0 || dr.sell.length > 0) && (
            <Note>
              Pour revenir à la cible : {[...dr.sell.map((r) => `alléger ${r.name} de ${chf(-r.gap, 0)} CHF`),
                ...dr.buy.map((r) => `renforcer ${r.name} de ${chf(r.gap, 0)} CHF`)].join(", ")}.
              Le 3a ne se vide pas à volonté : l'ajuster par les prochains versements.
            </Note>
          )}
        </>
      ) : <p className="text-[14px] text-muted">Aucune cible déclarée. Elle se déclare par classe d'actifs, en pourcentage.</p>}
      <AllocationSheet open={editing} onClose={() => setEditing(false)} s={s} />
    </Panel>
  );
}

function AllocationSheet({ open, onClose, s }: { open: boolean; onClose: () => void; s: Savings }) {
  const al = s.allocation;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(al.classes.map((c) => [c, al.targets[c] != null ? String(al.targets[c]) : ""])));
  const [error, setError] = useState("");
  const sum = Object.values(values).reduce((a, v) => a + (Number(v) || 0), 0);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await send("/api/allocation", { targets: values });
      toast.success("Allocation cible enregistrée");
      onClose();
    } catch (err) { setError((err as Error).message); }
  };
  const clear = async () => { await send("/api/allocation", { action: "clear" }); toast("Allocation cible effacée"); onClose(); };
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="Allocation cible"
           description="Par classe d'actifs. Les champs vides valent 0 ; la somme doit faire 100 %.">
      <form onSubmit={save} className="space-y-3">
        {al.classes.map((c) => (
          <label key={c} className="flex items-center gap-3">
            <span className="flex-1 text-[14px]">{c}</span>
            <input type="number" inputMode="decimal" step="0.1" min="0" max="100" value={values[c]}
                   placeholder={String(Math.round(al.current[c] ?? 0))}
                   onChange={(e) => setValues({ ...values, [c]: e.target.value })}
                   className="h-11 w-28 rounded-xl border border-hairline-2 bg-surface px-3 text-right text-[16px] num" />
            <span className="w-4 text-muted">%</span>
          </label>
        ))}
        <div className={cx("text-right text-[13px] num", Math.abs(sum - 100) < 0.05 ? "text-good" : "text-muted")}>total {sum.toFixed(1)} %</div>
        {error && <p className="text-[13px] text-critical" role="alert">{error}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" className="flex-1">Enregistrer</Button>
          {Object.keys(al.targets).length > 0 && <Button type="button" variant="ghost" onClick={clear}>Effacer</Button>}
        </div>
      </form>
    </Sheet>
  );
}

/* ---------------------------------------------------------------- crypto */

function Crypto({ s }: { s: Savings }) {
  const cx_ = s.crypto!;
  const rows = cx_.positions.filter((p) => (p.value_chf ?? 0) >= 0.5 || p.cost_chf >= 0.5);
  return (
    <Panel foldable defaultOpen={s.focus === "crypto"} title="Crypto, actif par actif"
           hint={`cours du ${frDate(cx_.as_of)} · Binance × BCE`}>
      <Table rows={rows} rowKey={(r) => r.symbol}
             cols={[
               { key: "symbol", label: "Actif", sort: (r) => r.symbol, render: (r) => r.symbol },
               { key: "qty", label: "Quantité", numeric: true, render: (r) => r.quantity.toPrecision(8).replace(/\.?0+$/, "") },
               { key: "rewards", label: "dont staking", numeric: true, wide: true, render: (r) => (r.rewards ? r.rewards.quantity.toPrecision(6).replace(/\.?0+$/, "") : "—") },
               { key: "price", label: "Cours", numeric: true, wide: true, render: (r) => (r.price_chf != null ? chf(r.price_chf) : "—") },
               { key: "value", label: "Valeur", numeric: true, sort: (r) => r.value_chf ?? 0, render: (r) => (r.value_chf != null ? chf(r.value_chf, 0) : "—") },
               { key: "cost", label: "Coût", numeric: true, render: (r) => chf(r.cost_chf, 0) },
               { key: "pnl", label: "Plus-value", numeric: true, render: (r) => {
                 const v = (r.value_chf ?? 0) - r.cost_chf;
                 return <span className={tone(v, 0.5)}>{signedChf(v)}</span>;
               } },
             ]} />
      <Note>
        Total {chf(cx_.value_chf, 0)} CHF pour un coût de {chf(cx_.cost_chf, 0)} CHF. Le coût est celui des coins encore détenus
        (coût moyen) ; les récompenses de staking sont du rendement, sans coût.
        {!cx_.calibration || !Object.keys(cx_.calibration).length ? " Leurs quantités sont reconstituées : l'export Revolut en perd la virgule." : ""}
        {cx_.sent.map((x) => ` ${x.quantity.toFixed(2)} ${x.symbol} (${chf(x.value_chf, 0)} CHF) envoyés hors de Revolut le ${frDate(x.day)}.`).join("")}
      </Note>
    </Panel>
  );
}

/* ------------------------------------------------------------------ fees */

function Fees({ s }: { s: Savings }) {
  const names: Record<string, string> = { swissquote: "Swissquote", ibkr: "IBKR", finpension: "3a finpension", crypto: "Crypto", titres: "Titres non cotés" };
  const rows = Object.entries(s.fees).filter(([k]) => k !== "total").map(([k, f]) => ({ k, ...f }));
  return (
    <Panel foldable defaultOpen={false} title="Frais sur la période"
           hint={`${chf(s.fees.total?.amount ?? 0)} CHF · hors frais internes des fonds`}>
      <Table rows={rows} rowKey={(r) => r.k} sortable={false}
             cols={[
               { key: "k", label: "Poche", render: (r) => names[r.k] ?? r.k },
               { key: "amount", label: "Frais", numeric: true, render: (r) => `${chf(r.amount)} CHF` },
               { key: "pct", label: "Part de la valeur", numeric: true, render: (r) => (r.pct != null ? `${r.pct.toFixed(2)} %` : "—") },
               { key: "detail", label: "Détail", render: (r) => (
                 <div className="text-[12.5px] text-ink-2">{r.detail}
                   {r.items.map((i, n) => <div key={n} className="text-muted">{frDate(i.date)} · {i.label} · {chf(i.amount)} CHF</div>)}
                 </div>) },
             ]} />
    </Panel>
  );
}

/* ------------------------------------------------------------------- tax */

function Tax({ s }: { s: Savings }) {
  const tax = s.tax!;
  const closed = tax.years.filter((y) => !y.partial);
  const est = tax.years.find((y) => y.partial);
  const ly = closed[closed.length - 1] ?? est!;
  const card = (label: string, value: ReactNode, sub: ReactNode, estimated?: boolean) => (
    <div className={cx("rounded-2xl p-4", estimated ? "border border-dashed border-hairline-2" : "bg-surface-2/60")}>
      <div className="eyebrow">{label}</div>
      <div className="num mt-1 text-[20px] font-semibold tracking-tight">{value}</div>
      <div className="mt-0.5 text-[12.5px] text-muted">{sub}</div>
    </div>
  );
  return (
    <Panel foldable defaultOpen={false} title="Pour la déclaration d'impôts"
           hint={`fortune au 31.12.${ly.year} : ${chf(ly.taxable, 0)} CHF${est && closed.length ? ` · ${est.year} estimée : ${chf(est.taxable, 0)} CHF` : ""}`}
           actions={<a href="/epargne/impots.xlsx" download className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-ink px-3 text-[13px] font-medium text-page no-underline"><Download size={14} />Exporter en xlsx</a>}>
      {est && closed.length > 0 && (
        <>
          <div className="eyebrow mb-2">{est.year} en cours · estimation au {frDate(est.day)}</div>
          <div className="mb-5 grid gap-3 sm:grid-cols-3">
            {card("Fortune imposable", `${chf(est.taxable, 0)} CHF`, `si le 31.12 était le ${frDate(est.day).slice(0, 5)}`, true)}
            {card("Revenus IBKR depuis janvier", `${chf(est.dividends + est.interest, 0)} CHF`,
              `${chf(est.dividends, 0)} de dividendes · ${chf(est.interest, 0)} d'intérêts${est.withheld ? ` · ${chf(est.withheld)} retenus aux US (DA-1)` : ""}`, true)}
            {card(`3a ${est.year}`, `${chf(est.pillar3a_paid ?? 0, 0)} / ${chf(est.ceiling_3a, 0)}`,
              est.ceiling_3a - (est.pillar3a_paid ?? 0) >= 1 ? `encore ${chf(est.ceiling_3a - (est.pillar3a_paid ?? 0), 0)} déductibles` : "plafond atteint", true)}
          </div>
        </>
      )}
      <div className="eyebrow mb-2">Dernière année close · 31.12.{ly.year}</div>
      <div className="grid gap-3 sm:grid-cols-3">
        {card("Fortune imposable", `${chf(ly.taxable, 0)} CHF`, "ces comptes, 3a exclu")}
        {card(`Revenus IBKR ${ly.year}`, `${chf(ly.dividends + ly.interest, 0)} CHF`,
          `${chf(ly.dividends, 0)} de dividendes · ${chf(ly.interest, 0)} d'intérêts${ly.withheld ? ` · ${chf(ly.withheld)} retenus aux US (DA-1)` : ""}`)}
        {card(`3a ${ly.year}`, `${chf(ly.pillar3a_paid ?? 0, 0)} CHF`, `versés, déductibles${ly.pillar3a_value != null ? ` · valeur ${chf(ly.pillar3a_value, 0)}` : ""}`)}
      </div>
      <div className="-mx-4 mt-5 overflow-x-auto sm:-mx-5">
        <table className="w-full min-w-[560px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-hairline">
              <th className="px-4 py-2 text-left text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted sm:px-5">Au 31 décembre</th>
              {tax.years.map((y) => (
                <th key={y.year} className={cx("px-3 py-2 text-right text-[11.5px] font-semibold uppercase tracking-[0.06em]", y.partial ? "text-muted italic" : "text-ink")}>
                  {y.year}{y.partial && <div className="font-normal normal-case tracking-normal">estimé au {frDate(y.day).slice(0, 5)}</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tax.rows.map((row) => {
              const held = row.cells.some((c) => c && c.value);
              return (
                <tr key={row.name} className={cx("border-b border-hairline", !held && "text-muted")}>
                  <td className="px-4 py-2 sm:px-5">{row.name}</td>
                  {row.cells.map((c, i) => (
                    <td key={i} className="num px-3 py-2 text-right">{c && c.value != null ? chf(c.value) : "—"}
                      {c?.detail && <div className="text-[11.5px] text-muted">{c.detail}</div>}</td>
                  ))}
                </tr>
              );
            })}
            <tr className="border-b border-hairline font-semibold">
              <td className="px-4 py-2 sm:px-5">Fortune imposable</td>
              {tax.years.map((y) => <td key={y.year} className="num px-3 py-2 text-right">{chf(y.taxable)}</td>)}
            </tr>
            {([["Dividendes IBKR", "dividends"], ["Intérêts IBKR", "interest"], ["Impôt US retenu (DA-1)", "withheld"],
               ["3a versé, déductible", "pillar3a_paid"], ["3a, valeur", "pillar3a_value"]] as const).map(([label, k]) => (
              <tr key={k} className="border-b border-hairline last:border-0">
                <td className="px-4 py-2 sm:px-5">{label}</td>
                {tax.years.map((y) => <td key={y.year} className="num px-3 py-2 text-right">{y[k] != null ? chf(y[k] as number) : "—"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>Valeurs de l'app : NAV du courtier, cours de marché, taux de change du relevé. L'administration retient ses propres cours de fin d'année : les chiffres en sont proches, pas identiques. Pour le 3a, l'attestation de la fondation fait foi.</Note>
    </Panel>
  );
}

/* ------------------------------------------------------------------ risk */

function Risk({ s }: { s: Savings }) {
  const rk = s.risk!;
  const { href } = useView();
  // The default follows the window (annual from a year on), so the URL only
  // carries a choice that differs from it.
  const auto = rk.yearly ? "annual" : "period";
  return (
    <Panel id="p-risk" foldable defaultOpen={false} title="Risque et statistiques" hint={`${rk.points} jours, mesurés chaque jour`}
           actions={<Segmented size="sm" label="Taux et ratios" value={rk.mode} options={s.options.stats}
                               hrefFor={(id) => href({ stats: id === auto ? null : id })} />}>
      <div className="-mx-4 overflow-x-auto sm:-mx-5">
        <table className="w-full min-w-[640px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-hairline">
              <th className="px-4 py-2 sm:px-5" />
              {rk.columns.map((c) => <th key={c} className="px-3 py-2 text-right text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rk.rows.map((row) => (
              <tr key={row.label} className="border-b border-hairline last:border-0">
                <td className="px-4 py-2 sm:px-5">{row.label}<div className="text-[11.5px] text-muted">{row.why}</div></td>
                {row.cells.map((c, i) => <td key={i} className={cx("num whitespace-nowrap px-3 py-2 text-right", c.text.startsWith("-") && "text-critical")}>{c.text}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        {rk.extrapolated && <><b className="text-ink-2">Extrapolé :</b> moins d'un an ramené à un an — quelques bons ou mauvais mois s'y lisent comme une année entière. </>}
        {rk.mode === "period" && "Sur la période : rendements, volatilité et ratios sur la fenêtre affichée, sans rien ramener à un an — ils ne se comparent qu'entre colonnes d'une même fenêtre. "}
        La colonne 3a mesure une estimation entre deux relevés.
        {rk.cash_share ? ` L'épargne totale compte ${Math.round(rk.cash_share * 100)} % de compte courant à rendement nul : sa volatilité est diluée d'autant.` : ""}
        {" "}Taux sans risque : 0,5 %.
      </Note>
    </Panel>
  );
}

/** Whether the unlisted shares declared on the tax page count: by default
 * yes, in the total, the curve and the returns; one click leaves them out. */
function TitresSwitch({ s }: { s: Savings }) {
  const { href } = useView();
  return (
    <Segmented size="sm" label="Titres non cotés" value={s.titres.counted ? "on" : "off"}
               options={[{ id: "on", label: "Titres comptés", title: `${chf(s.titres.value, 0)} CHF à leur valeur fiscale` },
                         { id: "off", label: "Sans les titres" }]}
               hrefFor={(id) => href({ titres: id === "on" ? null : "0" })} />
  );
}
