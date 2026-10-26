/** The assumed return and volatility: the barème drawn as a timeline and
 * edited period by period, what it does to a franc, the band's width, and
 * market scenarios as cards to apply in one click. Every figure here is the
 * server's (`plans.growth_path`); this file draws and edits. */
import { Bookmark, Plus, Sparkles, Trash2, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { AiBadge, aiBox, failed, useAi } from "@/components/assist/common";
import { Input } from "@/components/Form";
import { Button, Chip, Segmented, cx } from "@/components/ui";
import { ApiError, post } from "@/lib/api";
import { chf } from "@/lib/format";
import { planAction, type GrowthPath, type Market, type PocketRates, type Previsions } from "@/lib/previsions";
import { useView } from "@/lib/url";

import { useAction } from "./Plan";
import { ByYear, targetOf, type RateTarget } from "./Years";

type Row = { months: string; rate: string };

const pct = (r: number, digits = 1) =>
  `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r * 100).toFixed(digits).replace(/\.?0+$/, "").replace(".", ",")} %`;
const span = (months: number) => (months % 12 === 0 && months >= 12 ? `${months / 12} an${months > 12 ? "s" : ""}` : `${months} mois`);
const fromApplied = (t: RateTarget): Row[] =>
  t.segments.map(([m, r]) => ({ months: String(m), rate: String(Math.round(r * 10000) / 100) }));

/** A field with its unit inside, at a width that fits what it holds. */
function Unit({ unit, className, ...props }: React.ComponentProps<typeof Input> & { unit: string }) {
  return (
    <div className={cx("relative", className)}>
      <Input {...props} className="w-full pr-14 text-right" />
      <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12.5px] text-muted">{unit}</span>
    </div>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[14.5px] font-semibold">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** The barème laid along the horizon: one block per period, its width its
 * length, its tint its sign; past the declared periods, the last rate
 * carries on (hatched). */
function Timeline({ rows, horizon }: { rows: { months: number; rate: number }[]; horizon: number }) {
  const declared = rows.reduce((a, r) => a + r.months, 0);
  const total = Math.max(horizon, declared, 1);
  const tint = (r: number) => (r >= 0 ? "var(--good)" : "var(--critical)");
  const alpha = (r: number) => 0.18 + Math.min(Math.abs(r) / 0.2, 1) * 0.5;
  const last = rows[rows.length - 1];
  return (
    <div>
      <div className="relative flex h-9 overflow-hidden rounded-xl border border-hairline bg-surface-2/40">
        {rows.length === 0 && <span className="m-auto text-[12.5px] text-muted">aucun rendement : les placements restent à leur valeur</span>}
        {rows.map((r, i) => (
          <div key={i} title={`${pct(r.rate)} par an pendant ${span(r.months)}`}
               className="flex min-w-0 items-center justify-center border-r border-surface px-1 text-[12px] font-semibold"
               style={{ width: `${(r.months / total) * 100}%`, background: `color-mix(in srgb, ${tint(r.rate)} ${alpha(r.rate) * 100}%, transparent)` }}>
            <span className="truncate">{pct(r.rate)}</span>
          </div>
        ))}
        {last && declared < total && (
          <div title={`puis ${pct(last.rate)} par an, le dernier taux continue`}
               className="flex min-w-0 flex-1 items-center justify-center px-1 text-[12px] text-muted"
               style={{ backgroundImage: `repeating-linear-gradient(135deg, color-mix(in srgb, ${tint(last.rate)} 22%, transparent) 0 6px, transparent 6px 12px)` }}>
            <span className="truncate">puis {pct(last.rate)}</span>
          </div>
        )}
        {declared > horizon && (
          <span className="absolute inset-y-0 border-l-2 border-dashed border-ink-2" style={{ left: `${(horizon / total) * 100}%` }}
                title="fin de l'horizon affiché" />
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted num">
        <span>aujourd'hui</span>
        {declared > horizon && <span>horizon {span(horizon)}</span>}
        <span>{span(total)}</span>
      </div>
    </div>
  );
}

/** A franc's path under a barème: a line around the 1 it started from. */
function Spark({ path, height = 44 }: { path: GrowthPath; height?: number }) {
  const pts = path.points;
  const lo = Math.min(1, ...pts), hi = Math.max(1, ...pts);
  const y = (v: number) => height - 3 - ((v - lo) / (hi - lo || 1)) * (height - 6);
  const x = (i: number) => (i / Math.max(pts.length - 1, 1)) * 100;
  const color = path.end >= 1 ? "var(--good)" : "var(--critical)";
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }} aria-hidden>
      <line x1="0" x2="100" y1={y(1)} y2={y(1)} stroke="var(--axis)" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
      <polyline points={pts.map((v, i) => `${x(i)},${y(v)}`).join(" ")} fill="none" stroke={color} strokeWidth="1.75"
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

/** "1'000 placés → 1'104 dans 2 ans · ≈ +5 %/an", and the low point when
 * the path dips. */
function Effect({ path }: { path: GrowthPath }) {
  return (
    <p className="text-[13px] text-ink-2">
      1'000 CHF placés aujourd'hui → <b className="num text-ink">{chf(1000 * path.end, 0)}</b> dans {span(path.months)}
      {path.annual != null && <> · soit <span className="num">{pct(path.annual)}</span> par an en moyenne</>}
      {path.low < 1 && path.low_month > 0 && path.low_month < path.months && (
        <> · au plus bas <span className="num text-critical">{chf(1000 * path.low, 0)}</span> après {span(path.low_month)}</>
      )}
    </p>
  );
}

function Barème({ d, t, footer }: { d: Previsions; t: RateTarget; footer?: ReactNode }) {
  const { errors, busy, run } = useAction(d);
  const [rows, setRows] = useState<Row[]>(() => fromApplied(t));
  const parsed = rows.map((r) => ({ months: Number(r.months), rate: Number(r.rate.replace(",", ".")) / 100 }))
    .filter((r) => r.months > 0 && r.rate > -1 && r.rate < 1 && rows.length > 0);
  const applied = fromApplied(t);
  const dirty = JSON.stringify(rows) !== JSON.stringify(applied);
  const set = (i: number, k: keyof Row, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = () => run({ action: "rate", months: rows.length ? rows.map((r) => r.months) : [""],
                           rates: rows.length ? rows.map((r) => r.rate.replace(",", ".")) : [""], ...targetOf(t) },
    rows.length ? "Barème appliqué" : "Rendement retiré");
  return (
    <div>
      <Timeline rows={parsed} horizon={d.months} />
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); void save(); }} className="mt-4">
        <ol className="space-y-2">
          {rows.map((r, i) => (
            <li key={i}>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 sm:flex">
                <span className="col-span-3 text-[12.5px] font-medium text-ink-2 sm:w-16">{i === 0 ? "D'abord" : "Puis"}</span>
                <Unit unit="% / an" type="text" inputMode="decimal" value={r.rate} placeholder="4"
                      onChange={(e) => set(i, "rate", e.target.value)} className="sm:w-32"
                      aria-label={`Taux annuel de la période ${i + 1}`} invalid={!!errors[`rate-row-${i}`]} />
                <span className="hidden text-[12.5px] text-muted sm:inline">pendant</span>
                <Unit unit="mois" type="number" min="1" step="1" inputMode="numeric" value={r.months} placeholder="12"
                      onChange={(e) => set(i, "months", e.target.value)} className="sm:w-28"
                      aria-label={`Durée en mois de la période ${i + 1}`} invalid={!!errors[`rate-row-${i}`]} />
                <button type="button" aria-label={`Retirer la période ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}
                        className="rounded-lg p-1.5 text-muted transition hover:bg-surface-2 hover:text-critical"><X size={15} /></button>
              </div>
              {errors[`rate-row-${i}`] && <p className="mt-1 sm:ml-[4.5rem] text-[12.5px] text-critical">{errors[`rate-row-${i}`]}</p>}
            </li>
          ))}
        </ol>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" onClick={() => setRows([...rows, { months: "12", rate: rows[rows.length - 1]?.rate ?? "" }])}>
            <Plus size={14} />{rows.length ? "Ajouter une période" : "Déclarer un rendement"}
          </Button>
          <Button type="submit" size="sm" variant="primary" disabled={busy || !dirty}>Appliquer le barème</Button>
          {dirty && <span className="text-[12px] text-warn">modifié, pas encore appliqué</span>}
        </div>
        <p className="mt-2 text-[12px] text-muted">Taux annuel, au centième près, composé chaque mois ; après la dernière période, son taux continue. Il s'applique aux placements seuls : le cash ne capitalise jamais.</p>
      </form>
      {footer}
    </div>
  );
}

/** The assumed return of the target: typed year by year (the default) or
 * as periods of months, a constant rate in one click, and what the applied
 * barème does to 1'000 CHF. */
function Return({ d, t }: { d: Previsions; t: RateTarget }) {
  const { busy, run } = useAction(d);
  const [mode, setMode] = useState<"years" | "periods">("years");
  const constant = (rate: number | null) =>
    run({ action: "rate", months: [rate == null ? "" : "12"], rates: [rate == null ? "" : String(rate)], ...targetOf(t) },
      rate == null ? (t.pocket ? `${t.label} : valeur figée` : "Rendement retiré") : `${rate} % constant${t.pocket ? ` · ${t.label}` : ""}`);
  const footer = (
    <div className="mt-4 grid items-center gap-3 rounded-xl bg-surface-2/50 p-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
      <div>
        <div className="eyebrow">Barème appliqué{t.pocket ? ` à ${t.label}` : ""}, sur {span(d.months)}</div>
        <div className="mt-1"><Effect path={t.growth} /></div>
      </div>
      <Spark path={t.growth} />
    </div>
  );
  return (
    <Section title={t.pocket ? `Rendement supposé · ${t.label}` : "Rendement supposé"}
             aside={<Segmented size="sm" label="Façon de saisir le rendement" value={mode} onChange={setMode}
                               options={[{ id: "years", label: "Année par année" }, { id: "periods", label: "Par périodes" }]} />}>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[12px] text-muted">Constant :</span>
        {[null, 1, 2, 3, 4, 5, 6, 7, 8].map((r) => (
          <button key={String(r)} type="button" onClick={() => void constant(r)} disabled={busy}
                  className="rounded-full border border-hairline-2 px-2.5 py-0.5 text-[12px] text-ink-2 transition hover:bg-surface-2">
            {r == null ? (t.pocket ? "Aucun (figé)" : "Aucun") : `${r} %`}
          </button>
        ))}
      </div>
      {mode === "years" ? <ByYear d={d} t={t} footer={footer} /> : <Barème d={d} t={t} footer={footer} />}
    </Section>
  );
}

function Volatility({ d, t }: { d: Previsions; t: RateTarget }) {
  const { errors, busy, run } = useAction(d);
  const measured = t.volMeasured;
  const [mode, setMode] = useState<"measured" | "declared">(t.vol != null ? "declared" : "measured");
  const [vol, setVol] = useState(t.vol != null ? String(Math.round(t.vol * 1000) / 10).replace(".", ",") : "");
  const choose = (m: "measured" | "declared") => {
    setMode(m);
    if (m === "measured" && t.vol != null) void run({ action: "vol", amount: "", ...targetOf(t) }, "Volatilité mesurée");
  };
  const option = (m: "measured" | "declared", label: string, detail: ReactNode) => {
    const on = mode === m;
    return (
      <button type="button" role="radio" aria-checked={on} onClick={() => choose(m)}
              className={cx("flex flex-1 items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition",
                on ? "border-ink bg-surface-2" : "border-hairline-2 hover:bg-surface-2")}>
        <span className={cx("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border", on ? "border-ink" : "border-hairline-2")}>
          {on && <span className="size-2 rounded-full bg-ink" />}
        </span>
        <span className="min-w-0">
          <span className="block text-[13.5px] font-medium">{label}</span>
          <span className="block text-[12px] text-muted">{detail}</span>
        </span>
      </button>
    );
  };
  return (
    <Section title={t.pocket ? `Volatilité · ${t.label}` : "Volatilité"} aside={<span className="text-[12px] text-muted">la largeur de la zone ±1 écart-type</span>}>
      <div role="radiogroup" aria-label="Volatilité" className="flex flex-col gap-2 sm:flex-row">
        {option("measured", t.pocket ? `Mesurée sur ${t.label}` : "Mesurée sur tes poches", measured != null ? <span className="num">{(measured * 100).toFixed(1)} % par an</span> : "pas assez d'historique")}
        {option("declared", "Déclarée", t.vol != null ? <span className="num">{(t.vol * 100).toFixed(1)} % par an{t.vol === 0 ? " · aucune zone" : ""}</span> : "ta propre hypothèse")}
      </div>
      {mode === "declared" && (
        <form className="mt-3 flex flex-wrap items-center gap-2"
              onSubmit={(e) => { e.preventDefault(); void run({ action: "vol", amount: vol, ...targetOf(t) }, "Volatilité enregistrée"); }}>
          <Unit unit="% / an" id="plan-vol" type="text" inputMode="decimal" value={vol} placeholder="15" className="w-32"
                onChange={(e) => setVol(e.target.value)} invalid={!!errors["plan-vol"]} aria-label="Volatilité annuelle déclarée" />
          <Button type="submit" size="sm" disabled={busy || vol === ""}>Appliquer</Button>
          <span className={cx("text-[12px]", errors["plan-vol"] ? "text-critical" : "text-muted")}>
            {errors["plan-vol"] ?? "0 % = pas de zone ; la zone s'élargit en √t."}
          </span>
        </form>
      )}
    </Section>
  );
}

function MarketCard({ name, note, m, badge, busy, onApply, onDelete, pockets }: {
  name: string; note?: string; m: Market; badge?: string; busy: boolean; onApply: () => void; onDelete?: () => void;
  pockets?: { id: string; label: string; rate: number; vol: number }[];
}) {
  return (
    <div className="flex flex-col rounded-xl border border-hairline-2 p-3">
      <div className="flex items-start gap-2">
        <h4 className="min-w-0 flex-1 text-[13.5px] font-semibold leading-snug">{name}</h4>
        {badge && <Chip>{badge}</Chip>}
        {onDelete && (
          <button type="button" aria-label={`Supprimer ${name}`} onClick={onDelete}
                  className="-m-1 rounded-lg p-1 text-muted hover:text-critical"><Trash2 size={14} /></button>
        )}
      </div>
      {note && <p className="mt-0.5 text-[12px] leading-snug text-muted">{note}</p>}
      <div className="mt-2"><Spark path={m.path} height={40} /></div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted">
        <span>1'000 → <b className="num text-ink">{chf(1000 * m.path.end, 0)}</b> en {span(m.path.months)}</span>
        {m.path.low < 0.999 && <span>creux <span className="num text-critical">{chf(1000 * m.path.low, 0)}</span></span>}
      </div>
      <div className="mt-1 text-[11.5px] text-muted">
        {m.segments.map((s) => `${pct(s.rate)} · ${span(s.months)}`).join(" → ")}
        {m.vol != null && ` · vol ${(m.vol * 100).toFixed(0)} %`}
        {pockets && pockets.length > 0 && " · le reste"}
      </div>
      {pockets && pockets.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[11.5px] text-ink-2">
          {pockets.map((p) => (
            <li key={p.id} className="flex justify-between gap-2">
              <span className="truncate">{p.label}</span>
              <span className="num shrink-0">{pct(p.rate)} · vol {(p.vol * 100).toFixed(0)} %</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-auto pt-2.5">
        <Button size="sm" className="w-full" disabled={busy} onClick={onApply}>
          Appliquer{m.months ? ` · horizon ${span(m.months)}` : ""}
        </Button>
      </div>
    </div>
  );
}

function Markets({ d, t }: { d: Previsions; t: RateTarget }) {
  const { errors, busy, run } = useAction(d);
  const [name, setName] = useState("");
  const to = t.pocket ? ` à ${t.label}` : "";
  return (
    <Section title="Scénarios de marché" aside={<span className="text-[12px] text-muted">un barème complet d'un clic{to ? `, appliqué${to}` : ""} · des formes, pas des conseils</span>}>
      {/* A row that scrolls card by card on a phone; a grid from the tablet up. */}
      <div className="-mx-4 flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-4 pb-1 no-scrollbar sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 xl:grid-cols-3 [&>*]:w-[78%] [&>*]:shrink-0 [&>*]:snap-center sm:[&>*]:w-auto">
        {d.builtin_scenarios.map((s) => (
          <MarketCard key={s.key} name={s.label} note={s.note} m={s} busy={busy}
                      pockets={t.pocket ? s.pockets.filter((p) => p.id === t.pocket) : s.pockets}
                      onApply={() => run({ action: "scenario-apply", scenario: `builtin:${s.key}`, ...targetOf(t) }, `« ${s.label} » appliqué${to}`)} />
        ))}
        {d.plan.scenarios.map((s) => (
          <MarketCard key={s.name} name={s.name} m={s} badge="à toi" busy={busy}
                      onApply={() => run({ action: "scenario-apply", scenario: `saved:${s.name}`, ...targetOf(t) }, `« ${s.name} » appliqué${to}`)}
                      onDelete={() => run({ action: "scenario-delete", name: s.name }, "Barème supprimé")} />
        ))}
        <form className="flex flex-col justify-center gap-2 rounded-xl border border-dashed border-hairline-2 p-3"
              onSubmit={async (e) => { e.preventDefault(); if (await run({ action: "scenario-save", name, ...targetOf(t) }, `Barème enregistré sous « ${name} »`)) setName(""); }}>
          <div className="flex items-center gap-1.5 text-[13.5px] font-semibold"><Bookmark size={14} />Garder le barème {t.pocket ? `de ${t.label}` : "actuel"}</div>
          <p className="text-[12px] text-muted">Avec sa volatilité et l'horizon affiché, pour le rappeler d'un clic.</p>
          <div className="flex gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="Nom"
                   aria-label="Nom sous lequel garder le barème actuel" invalid={!!errors["scenario-save"]} />
            <Button size="sm" type="submit" disabled={!name.trim() || busy}>Garder</Button>
          </div>
          {errors["scenario-save"] && <p className="text-[12px] text-critical">{errors["scenario-save"]}</p>}
        </form>
      </div>
      {errors["scenario-apply"] && <p className="mt-2 text-[12.5px] text-critical">{errors["scenario-apply"]}</p>}
      <p className="mt-2 text-[12px] text-muted">Communs à tous les plans. Appliquer copie le barème dans le plan affiché{to ? `, pour ${t.label} seulement` : ""}, où il reste modifiable.</p>
    </Section>
  );
}

interface Hypothesis {
  supported: boolean; note?: string; name?: string; source?: "phrase" | "propose";
  segments?: { months: number; rate: number }[]; vol?: number | null; horizon?: number | null;
  summary?: string; path?: GrowthPath; current?: GrowthPath;
}

const EXAMPLES = [
  "Un krach de 30 % l'an prochain, puis 6 % par an",
  "Prudent pendant 3 ans, puis comme le marché mondial",
  "5 % par an sur 20 ans, avec une volatilité de 15 %",
];

/** A market hypothesis in a sentence: the model reads it into a barème, the
 * server checks it and draws what it does, the click applies it -- and the
 * toast undoes it. */
function InWords({ d, t }: { d: Previsions; t: RateTarget }) {
  const ai = useAi();
  const { href, navigate } = useView();
  const [sentence, setSentence] = useState("");
  const [busy, setBusy] = useState(false);
  const [h, setH] = useState<Hypothesis | null>(null);
  if (!ai?.enabled) return null;
  const ask = async (e?: FormEvent, text = sentence) => {
    e?.preventDefault();
    if (!text.trim()) return;
    setSentence(text);
    setBusy(true);
    try {
      setH(await post<Hypothesis>(`/api/ai/rates?months=${d.months}`, { sentence: text }));
    } catch (err) {
      const data = err instanceof ApiError ? err.data as Hypothesis | undefined : undefined;
      if (data && data.supported === false) setH(data);
      else failed("La phrase n'a pas pu être lue", err);
    } finally {
      setBusy(false);
    }
  };
  const apply = async (keep: boolean) => {
    if (!h?.segments) return;
    const before = { months: t.segments.map(([m]) => String(m)), rates: t.segments.map(([, r]) => String(Math.round(r * 10000) / 100)), vol: t.vol, own: t.own };
    setBusy(true);
    try {
      let r = await planAction(d.months, { action: "rate", months: h.segments.map((s) => String(s.months)), rates: h.segments.map((s) => String(Math.round(s.rate * 10000) / 100)), ...targetOf(t) });
      if (!r.errors && h.vol != null) r = await planAction(d.months, { action: "vol", amount: String(Math.round(h.vol * 1000) / 10), ...targetOf(t) });
      if (!r.errors && keep && h.name) r = await planAction(h.horizon ?? d.months, { action: "scenario-save", name: h.name });
      if (r.errors) { toast.error("Non appliqué", { description: Object.values(r.errors)[0] }); return; }
      toast.success(`« ${h.name} » appliqué${keep ? " et gardé" : ""}`, {
        action: { label: "Annuler", onClick: async () => {
          if (t.pocket && !before.own) {
            await planAction(d.months, { action: "pocket-common", ...targetOf(t) });
          } else {
            await planAction(d.months, { action: "rate", months: before.months.length ? before.months : [""], rates: before.rates.length ? before.rates : [""], ...targetOf(t) });
            await planAction(d.months, { action: "vol", amount: before.vol != null ? String(Math.round(before.vol * 1000) / 10) : "", ...targetOf(t) });
          }
          toast("Barème d'avant rétabli");
        } },
      });
      if (h.horizon) navigate(href({ months: h.horizon }, { keep: ["months", "wealth", "scale", "yscale", "split"] }), { preventScrollReset: true });
      setH(null);
      setSentence("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section title="Décrire en mots" aside={<AiBadge>assistant</AiBadge>}>
      <form onSubmit={ask} className="flex flex-wrap gap-2">
        <Input value={sentence} onChange={(e) => setSentence(e.target.value)} maxLength={300} className="min-w-[14rem] flex-1"
               placeholder="Ex. un krach de 30 % l'an prochain puis 6 % par an" aria-label="L'hypothèse de marché, en une phrase" />
        <Button type="submit" disabled={busy || !sentence.trim()}><Sparkles size={14} />{busy ? "Lecture…" : "Traduire"}</Button>
      </form>
      {!h && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" disabled={busy} onClick={() => void ask(undefined, x)}
                    className="rounded-full border border-hairline-2 px-2.5 py-1 text-[12px] text-ink-2 transition hover:bg-surface-2">{x}</button>
          ))}
        </div>
      )}
      {h && !h.supported && <p className="mt-3 text-[13px] text-ink-2">{h.note}</p>}
      {h?.supported && h.segments && h.path && h.current && (
        <div className={cx(aiBox, "mt-3 space-y-3")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-[14.5px] font-semibold">{h.name}</h4>
            <AiBadge>{h.source === "propose" ? "chiffres proposés, à vérifier" : "chiffres de ta phrase"}</AiBadge>
          </div>
          {h.note && <p className="text-[12.5px] text-ink-2">{h.note}</p>}
          <Timeline rows={h.segments} horizon={h.path.months} />
          <div className="grid items-center gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <div className="space-y-1 text-[13px]">
              <Effect path={h.path} />
              <p className="text-muted">Avec le barème actuel : <span className="num">{chf(1000 * h.current.end, 0)}</span> sur la même durée.</p>
              <p className="text-[12px] text-muted">
                Volatilité : {h.vol != null ? <span className="num">{(h.vol * 100).toFixed(0)} % par an</span> : "inchangée"}
                {h.horizon ? <> · horizon {span(h.horizon)}</> : null}
              </p>
            </div>
            <Spark path={h.path} />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setH(null)}>Écarter</Button>
            <Button size="sm" disabled={busy} onClick={() => void apply(true)}><Bookmark size={14} />Appliquer et garder</Button>
            <Button size="sm" variant="primary" disabled={busy} onClick={() => void apply(false)}>Appliquer</Button>
          </div>
          <p className="text-[11.5px] text-muted">Le modèle lit la phrase ; les montants ci-dessus sont calculés par l'app. Rien ne change avant le clic.</p>
        </div>
      )}
    </Section>
  );
}

/** Which barème the panel edits: the common one, or one pocket's. Each
 * pocket says what it follows; editing a pocket that follows the common
 * barème gives it its own. */
function PocketPicker({ d, pockets, pick, onPick }: {
  d: Previsions; pockets: PocketRates[]; pick: string; onPick: (id: string) => void;
}) {
  const common = d.plan.rate_segments;
  const commonLabel = common.length ? (common.length === 1 ? `${pct(common[0][1], 2)} par an` : `${common.length} périodes`) : "aucun rendement";
  const item = (id: string, label: string, sub: string, slot: number | null, status?: string) => {
    const on = id === pick;
    return (
      <button key={id} type="button" role="radio" aria-checked={on} onClick={() => onPick(id)}
              className={cx("flex min-w-[9.5rem] shrink-0 snap-start flex-col items-start rounded-xl border px-3 py-2 text-left transition sm:min-w-0",
                on ? "border-ink bg-surface-2" : "border-hairline-2 hover:bg-surface-2")}>
        <span className="flex w-full items-center gap-1.5 text-[13.5px] font-medium">
          {slot != null && <span className="size-2.5 shrink-0 rounded-full" style={{ background: `var(--s${slot})` }} />}
          <span className="truncate">{label}</span>
        </span>
        <span className="num text-[12px] text-muted">{sub}</span>
        {status && <span className={cx("mt-0.5 text-[11.5px]", status === "barème commun" ? "text-muted" : "font-medium text-ink-2")}>{status}</span>}
      </button>
    );
  };
  return (
    <div role="radiogroup" aria-label="Poche dont on règle le rendement"
         className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 no-scrollbar sm:mx-0 sm:grid sm:grid-cols-3 sm:px-0 lg:grid-cols-5">
      {item("all", "Barème commun", commonLabel, null, "les poches sans le leur")}
      {pockets.map((p) => item(p.id, p.label, `${chf(p.value, 0)} CHF`, p.slot,
        !p.own ? "barème commun" : p.rate_segments.length === 0 ? "valeur figée" : "son propre barème"))}
    </div>
  );
}

function PocketStatus({ d, p }: { d: Previsions; p: PocketRates }) {
  const { busy, run } = useAction(d);
  const fixed = p.own && p.rate_segments.length === 0;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-surface-2/60 px-3 py-2.5 text-[13px] text-ink-2">
      <span className="min-w-0 flex-1">
        {!p.own ? <><b className="text-ink">{p.label}</b> suit le barème commun. Le régler ici lui donne le sien, le commun ne change pas.</>
          : fixed && p.fixed_by_default ? <><b className="text-ink">{p.label}</b> garde sa valeur déclarée : aucun marché ne les cote. Donne-leur un rendement si tu en attends un.</>
          : fixed ? <><b className="text-ink">{p.label}</b> reste à sa valeur : aucun rendement pour elle.</>
          : <><b className="text-ink">{p.label}</b> a son propre barème : {p.summary}.</>}
      </span>
      {p.own ? (
        <Button size="sm" disabled={busy} onClick={() => void run({ action: "pocket-common", rate_pocket: p.id }, `${p.label} suit le barème commun`)}>
          Suivre le barème commun
        </Button>
      ) : (
        <Button size="sm" disabled={busy} onClick={() => void run({ action: "pocket-own", rate_pocket: p.id }, `${p.label} a son propre barème`)}>
          Partir du commun
        </Button>
      )}
    </div>
  );
}

/** Keyed on what is applied, so an apply from a card refills the rows. */
export function RateSettings({ d }: { d: Previsions }) {
  const pockets = d.wealth?.pockets_rates ?? [];
  const [pick, setPick] = useState("all");
  const p = pockets.find((x) => x.id === pick);
  const t: RateTarget = p
    ? { pocket: p.id, label: p.label, own: p.own, segments: p.rate_segments, years: p.rate_years,
        vol: p.vol, volMeasured: p.vol_measured, growth: p.growth }
    : { pocket: null, label: "toutes les poches", own: true, segments: d.plan.rate_segments, years: d.plan.rate_years,
        vol: d.plan.vol, volMeasured: d.wealth?.vol_measured ?? null, growth: d.growth };
  const key = JSON.stringify([pick, t.segments, t.vol, t.years.length, d.months]);
  return (
    <div className="space-y-3">
      {pockets.length > 0 && <PocketPicker d={d} pockets={pockets} pick={pick} onPick={setPick} />}
      {p && <PocketStatus d={d} p={p} />}
      <InWords d={d} t={t} />
      <Return key={`r${key}`} d={d} t={t} />
      <Volatility key={`v${key}`} d={d} t={t} />
      <Markets d={d} t={t} />
    </div>
  );
}
