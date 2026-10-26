/** The plan, edited in place: what a month brings and costs, the one-offs
 * on a timeline, the scheduled transfers as a sentence, the suggestions.
 * Each edit goes through `/api/previsions`, which refuses with the reason
 * per field -- the typed value stays. */
import { ArrowRight, CalendarClock, Check, Pencil, Plus, Repeat, RotateCcw, Sparkles, Trash2, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Field, Input, Select } from "@/components/Form";
import { Button, Card, Chip, cx } from "@/components/ui";
import { MONTHS, chf, frDate, plural } from "@/lib/format";
import { planAction, type FieldErrors, type Previsions } from "@/lib/previsions";
import { useView } from "@/lib/url";

import { PlanHeader } from "./Scenarios";

export function useAction(d: Previsions) {
  const { href, navigate } = useView();
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const run = async (body: Record<string, unknown>, done?: string) => {
    setBusy(true);
    try {
      const r = await planAction(d.months, body);
      if (r.errors) { setErrors(r.errors); return false; }
      setErrors({});
      if (done) toast.success(done);
      if (r.months) navigate(href({ months: r.months }, { keep: ["months", "wealth", "scale", "yscale", "split"] }), { preventScrollReset: true });
      return true;
    } catch (e) {
      toast.error("L'enregistrement a échoué", { description: (e as Error).message });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { errors, busy, run };
}

/** What each nature of one-off is called on a pill, and its tint. */
const NATURES: Record<string, { short: string; color: string; note: string }> = {
  "": { short: "Dépense", color: "var(--warn)", note: "l'argent est dépensé" },
  "3a": { short: "Vers le 3a", color: "var(--s3)", note: "sort du cash, reste dans le patrimoine, hors impôt" },
  taxable: { short: "Vers le placement", color: "var(--s1)", note: "sort du cash, reste dans le patrimoine" },
};

function Block({ icon, title, hint, actions, children, className }: {
  icon: ReactNode; title: string; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <Card className={cx("p-4 sm:p-5", className)}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-surface-2 text-ink-2">{icon}</span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-tight">{title}</h3>
          {hint && <p className="mt-0.5 text-[12.5px] text-muted">{hint}</p>}
        </div>
        {actions}
      </div>
      <div className="mt-4">{children}</div>
    </Card>
  );
}

/** One choice among a few, as pills: a nature, a pocket. */
function Pills({ value, options, onChange, label }: {
  value: string; options: { id: string; label: string; color?: string }[]; onChange: (id: string) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button key={o.id} type="button" role="radio" aria-checked={on} onClick={() => onChange(o.id)}
                  className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12.5px] transition",
                    on ? "border-ink bg-surface-2 font-semibold text-ink" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
            {o.color && <i className="inline-block size-2 rounded-full" style={{ background: o.color }} />}{o.label}
          </button>
        );
      })}
    </div>
  );
}

export function PlanEditor({ d }: { d: Previsions }) {
  return (
    <section id="p-plan" className="scroll-mt-24">
      <PlanHeader d={d} />
      <div className="space-y-4 sm:space-y-5">
        <Monthly d={d} />
        <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
          <OneOffs d={d} />
          <Series d={d} />
        </div>
        {(d.suggestions.length > 0 || d.plan.ignored.length > 0) && <Suggestions d={d} />}
      </div>
    </section>
  );
}

/* --------------------------------------------------------- the usual month */

function Monthly({ d }: { d: Previsions }) {
  const p = d.projection;
  return (
    <Card className="overflow-hidden">
      <div className="grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)]">
        <AmountCell d={d} action="income" field="plan-income" title="Revenu mensuel" value={p.income} declared={d.plan.income}
                    history={p.income_source === "declared" ? null : p.income} tone="text-good" sign="+"
                    historyNote="la médiane de l'historique" />
        <AmountCell d={d} action="spend" field="plan-spend" title="Dépense de base" value={p.baseline} declared={d.plan.spend}
                    history={p.baseline_history} tone="text-ink" sign="−"
                    historyNote="la médiane de l'historique, hors pics saisonniers" />
        <div className="border-t border-hairline bg-surface-2/40 p-4 sm:border-l sm:border-t-0 sm:p-5">
          <div className="eyebrow">Reste chaque mois</div>
          <div className={cx("num mt-1.5 text-[26px] font-semibold leading-none tracking-[-0.03em]", p.margin >= 0 ? "text-good" : "text-critical")}>
            {p.margin >= 0 ? "+" : "−"}{chf(Math.abs(p.margin), 0)}<span className="ml-1 text-[12px] font-medium tracking-normal text-muted">CHF</span>
          </div>
          <p className="mt-1.5 text-[12px] text-muted">avant ponctuels et versements · c'est ce qui fait monter le cash d'un mois ordinaire</p>
        </div>
      </div>
    </Card>
  );
}

function AmountCell({ d, action, field, title, value, declared, history, tone, sign, historyNote }: {
  d: Previsions; action: string; field: string; title: string; value: number; declared: number | null;
  history: number | null; tone: string; sign: string; historyNote: string;
}) {
  const { errors, busy, run } = useAction(d);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(declared != null ? String(declared) : String(Math.round(value)));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (await run({ action, amount: text }, `${title} : ${chf(Number(text), 0)} CHF`)) setEditing(false);
  };
  return (
    <div className={cx("border-hairline p-4 sm:border-r sm:p-5", action === "spend" && "border-t sm:border-t-0")}>
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{title}</span>
        <Chip>{declared != null ? "déclaré" : "historique"}</Chip>
      </div>
      {editing ? (
        <form onSubmit={save} className="mt-2">
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Input id={field} autoFocus type="number" inputMode="decimal" step="0.01" min="0" value={text}
                     onChange={(e) => setText(e.target.value)} invalid={!!errors[field]} className="pr-16 text-right"
                     aria-label={`${title}, CHF par mois`} />
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12.5px] text-muted">CHF / mois</span>
            </div>
            <Button type="submit" variant="primary" disabled={busy}><Check size={15} /></Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)} aria-label="Annuler"><X size={15} /></Button>
          </div>
          {errors[field] && <p role="alert" className="mt-1.5 text-[12px] text-critical">{errors[field]}</p>}
        </form>
      ) : (
        <button type="button" onClick={() => setEditing(true)} className="group mt-1.5 flex items-baseline gap-1.5 text-left"
                aria-label={`Modifier : ${title}`}>
          <span className={cx("num text-[26px] font-semibold leading-none tracking-[-0.03em]", tone)}>{sign}{chf(value, 0)}</span>
          <span className="text-[12px] text-muted">CHF</span>
          <Pencil size={13} className="ml-1 text-muted opacity-0 transition group-hover:opacity-100" />
        </button>
      )}
      <p className="mt-1.5 text-[12px] text-muted">
        {declared != null
          ? <>Déclaré.{history != null && <> L'historique dit {chf(history, 0)}. <button type="button" disabled={busy}
              className="inline-flex items-center gap-1 font-medium text-ink-2 underline-offset-2 hover:underline"
              onClick={() => void run({ action, amount: "" }, `${title} : retour à l'historique`)}><RotateCcw size={11} />Revenir à l'historique</button></>}</>
          : <>{historyNote[0].toUpperCase() + historyNote.slice(1)}. Clique le montant pour en déclarer un.</>}
      </p>
    </div>
  );
}

/* --------------------------------------------------------------- one-offs */

function OneOffs({ d }: { d: Previsions }) {
  const { errors, busy, run } = useAction(d);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ date: "", label: "", amount: "", destination: "" });
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await run({ action: "add", ...form }, `« ${form.label} » ajouté`)) {
      setForm({ date: "", label: "", amount: "", destination: form.destination });
      setAdding(false);
    }
  };
  // By month, in order: the plan reads as a calendar.
  const byMonth = new Map<string, Previsions["plan"]["declared"]>();
  [...d.plan.declared].sort((a, b) => (a.date || `${a.month}-99`).localeCompare(b.date || `${b.month}-99`))
    .forEach((e) => byMonth.set(e.month, [...(byMonth.get(e.month) ?? []), e]));
  const indexOf = (e: Previsions["plan"]["declared"][number]) => d.plan.declared.indexOf(e) + 1;
  return (
    <Block icon={<CalendarClock size={16} />} title="Ponctuels"
           hint={d.plan.declared.length ? plural(d.plan.declared.length, "ponctuel déclaré", "ponctuels déclarés") : "impôts, assurance, un voyage, un virement au 3a"}
           actions={!adding && <Button size="sm" onClick={() => setAdding(true)}><Plus size={14} />Ajouter</Button>}>
      {adding && (
        <form onSubmit={add} className="mb-4 space-y-3 rounded-2xl border border-hairline-2 bg-surface-2/40 p-3.5">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem]">
            <Field label="Quoi" error={errors["oneoff-label"]}>
              {(id) => <Input id={id} autoFocus required placeholder="Ex. Impôts 2027" value={form.label}
                              onChange={(e) => setForm({ ...form, label: e.target.value })} invalid={!!errors["oneoff-label"]} />}
            </Field>
            <Field label="Montant, CHF" error={errors["oneoff-amount"]}>
              {(id) => <Input id={id} type="number" inputMode="decimal" step="0.01" min="0.01" required value={form.amount}
                              className="text-right" onChange={(e) => setForm({ ...form, amount: e.target.value })} invalid={!!errors["oneoff-amount"]} />}
            </Field>
          </div>
          <Field label="Quand" error={errors["oneoff-date"]}>
            {(id) => <div className="sm:w-48"><Input id={id} type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
                            invalid={!!errors["oneoff-date"]} /></div>}
          </Field>
          <div>
            <div className="mb-1.5 text-[12.5px] font-medium text-ink-2">Nature</div>
            <Pills label="Nature" value={form.destination} onChange={(id) => setForm({ ...form, destination: id })}
                   options={d.destinations.map((x) => ({ id: x.id, label: NATURES[x.id]?.short ?? x.label, color: NATURES[x.id]?.color }))} />
            <p className="mt-1.5 text-[12px] text-muted">{NATURES[form.destination]?.note}</p>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Annuler</Button>
            <Button type="submit" variant="primary" disabled={busy}><Plus size={15} />Ajouter</Button>
          </div>
        </form>
      )}
      {byMonth.size === 0 && !adding && (
        <p className="rounded-xl border border-dashed border-hairline-2 px-3 py-4 text-center text-[13px] text-muted">
          Rien de déclaré. Une dépense rare, un virement à venir : une ligne à sa date.
        </p>
      )}
      <ol className="space-y-3">
        {[...byMonth].map(([month, entries]) => (
          <li key={month}>
            <div className="mb-1 flex items-baseline justify-between text-[12px]">
              <span className="font-semibold capitalize text-ink-2">{MONTHS[Number(month.slice(5, 7)) - 1]} {month.slice(0, 4)}</span>
              <span className="num text-muted">−{chf(entries.reduce((a, e) => a + e.amount, 0), 0)}</span>
            </div>
            <ul className="divide-y divide-hairline rounded-xl border border-hairline">
              {entries.map((e) => <Declared key={`${e.month}-${e.label}`} d={d} e={e} index={indexOf(e)} />)}
            </ul>
          </li>
        ))}
      </ol>
    </Block>
  );
}

function Declared({ d, e, index }: { d: Previsions; e: Previsions["plan"]["declared"][number]; index: number }) {
  const { errors, run } = useAction(d);
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(String(e.amount));
  const nature = NATURES[e.transfer || ""] ?? NATURES[""];
  const saveAmount = async (ev: FormEvent) => {
    ev.preventDefault();
    if (await run({ action: "amount", month: e.month, label: e.label, amount }, "Montant modifié")) setEditing(false);
  };
  return (
    <li className="px-3 py-2.5 text-[13.5px]">
      <div className="flex items-center gap-2.5">
        <i className="inline-block h-8 w-1 shrink-0 rounded-full" style={{ background: nature.color }} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{e.label}{e.seasonal ? <span className="ml-1.5 text-[11.5px] font-normal text-muted">· suggéré</span> : null}</div>
          <div className="num text-[12px] text-muted">{e.date ? frDate(e.date) : "dans le mois"} · {nature.short.toLowerCase()}</div>
        </div>
        {editing ? (
          <form onSubmit={saveAmount} className="flex items-center gap-1">
            <Input autoFocus type="number" inputMode="decimal" step="0.01" min="0.01" value={amount} onChange={(x) => setAmount(x.target.value)}
                   aria-label={`Montant de « ${e.label} »`} className="w-28 text-right" invalid={!!errors[`amount-${index}`]} />
            <Button size="sm" type="submit" variant="primary" aria-label="Enregistrer le montant"><Check size={14} /></Button>
          </form>
        ) : (
          <button type="button" onClick={() => setEditing(true)} aria-label={`Modifier le montant de « ${e.label} »`}
                  className="num rounded-lg px-1.5 py-1 font-semibold hover:bg-surface-2">−{chf(e.amount, 0)}</button>
        )}
        <button type="button" aria-label={`Supprimer « ${e.label} »`} className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-critical"
                onClick={() => run({ action: "delete", month: e.month, label: e.label }, `« ${e.label} » supprimé`)}>
          <Trash2 size={15} />
        </button>
      </div>
      {errors[`amount-${index}`] && <p className="mt-1 text-[12.5px] text-critical">{errors[`amount-${index}`]}</p>}
      {editing && (
        <div className="mt-2 pl-3.5">
          <Pills label={`Nature de « ${e.label} »`} value={e.transfer || ""}
                 onChange={(id) => void run({ action: "destination", month: e.month, label: e.label, destination: id }, "Nature modifiée")}
                 options={d.destinations.map((x) => ({ id: x.id, label: NATURES[x.id]?.short ?? x.label, color: NATURES[x.id]?.color }))} />
        </div>
      )}
    </li>
  );
}

/* ----------------------------------------------------- scheduled transfers */

type SeriesFields = { amount: string; every: string; months: string; start: string; pocket: string };

/** "450 mois" as a reader says it: "37 ans et 6 mois". */
function span(months: number): string {
  const years = Math.floor(months / 12), rest = months % 12;
  const parts = [years ? `${years} an${years > 1 ? "s" : ""}` : "", rest ? `${rest} mois` : ""].filter(Boolean);
  return parts.join(" et ") || "0 mois";
}

/** One series as the sentence it is -- to add one, or to edit one in place. */
function SeriesForm({ d, initial, errors, busy, submit, cancel, editing }: {
  d: Previsions; initial: SeriesFields; errors: Record<string, string>; busy: boolean;
  submit: (f: SeriesFields) => void; cancel: () => void; editing?: boolean;
}) {
  const [f, setF] = useState(initial);
  const fieldError = ["contrib-amount", "contrib-every", "contrib-months", "contrib-start", "contrib-pocket"].map((k) => errors[k]).find(Boolean);
  const months = Number(f.months);
  return (
    <form onSubmit={(e: FormEvent) => { e.preventDefault(); submit(f); }}
          className={cx("rounded-2xl border border-hairline-2 bg-surface-2/40 p-3.5", !editing && "mb-4")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-[14px]">
        <span>Verser</span>
        <div className="relative w-32">
          <Input autoFocus type="text" inputMode="decimal" required value={f.amount} placeholder="500"
                 onChange={(e) => setF({ ...f, amount: e.target.value })} invalid={!!errors["contrib-amount"]}
                 aria-label="Montant de chaque versement" className="pr-11 text-right" />
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12.5px] text-muted">CHF</span>
        </div>
        <div className="w-44">
          <Select value={f.every} onChange={(e) => setF({ ...f, every: e.target.value })} aria-label="Cadence">
            {d.every_options.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
          </Select>
        </div>
        <span>pendant</span>
        <div className="relative w-28">
          <Input type="number" inputMode="numeric" min="1" step="1" required value={f.months} onChange={(e) => setF({ ...f, months: e.target.value })}
                 invalid={!!errors["contrib-months"]} aria-label="Durée en mois" className="pr-12 text-right" />
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12.5px] text-muted">mois</span>
        </div>
        {months >= 12 && <span className="text-[12px] text-muted">soit {span(months)}</span>}
        <span>vers</span>
        <Pills label="Vers" value={f.pocket} onChange={(id) => setF({ ...f, pocket: id })}
               options={d.pockets.map((x) => ({ id: x.id, label: x.id === "3a" ? "le 3a" : "le placement", color: NATURES[x.id]?.color }))} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
        <span>à partir de</span>
        <div className="w-44">
          <Input type="month" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} invalid={!!errors["contrib-start"]}
                 aria-label="Premier mois" />
        </div>
        <span className="text-[12px] text-muted">vide = le mois prochain</span>
      </div>
      {fieldError && <p role="alert" className="mt-2 text-[12.5px] text-critical">{fieldError}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={cancel}>Annuler</Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {editing ? "Enregistrer" : <><Plus size={15} />Ajouter la série</>}
        </Button>
      </div>
    </form>
  );
}

function Series({ d }: { d: Previsions }) {
  const { errors, busy, run } = useAction(d);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const blank: SeriesFields = { amount: "", every: "month", months: "24", start: "", pocket: d.pockets[0]?.id ?? "3a" };
  const fieldsOf = (c: Previsions["plan"]["contributions"][number]): SeriesFields =>
    ({ amount: String(c.amount), every: c.every, months: String(c.months), start: c.start, pocket: c.pocket });
  const pocketName = (id: string) => (id === "3a" ? "le 3a" : "le placement");

  const add = async (f: SeriesFields) => {
    if (await run({ action: "contrib", ...f }, "Série ajoutée")) setAdding(false);
  };
  const save = async (i: number, f: SeriesFields) => {
    const before = fieldsOf(d.plan.contributions[i]);
    if (await run({ action: "contrib", index: i, ...f })) {
      setEditing(null);
      toast.success("Série modifiée", {
        action: { label: "Annuler", onClick: async () => {
          await planAction(d.months, { action: "contrib", index: i, ...before });
          toast("Série d'avant rétablie");
        } },
      });
    }
  };
  const remove = async (i: number) => {
    const c = d.plan.contributions[i];
    if (await run({ action: "contrib-del", pocket: c.pocket, amount: c.amount, every: c.every, months: c.months, start: c.start })) {
      toast.success("Série retirée", {
        action: { label: "Annuler", onClick: async () => {
          await planAction(d.months, { action: "contrib", ...fieldsOf(c) });
          toast("Série rétablie");
        } },
      });
    }
  };
  return (
    <Block icon={<Repeat size={16} />} title="Versements programmés"
           hint={d.plan.contributions.length ? plural(d.plan.contributions.length, "série", "séries") : "un virement qui revient : chaque mois vers le placement, chaque année au 3a"}
           actions={!adding && editing === null && <Button size="sm" onClick={() => setAdding(true)}><Plus size={14} />Ajouter</Button>}>
      {adding && <SeriesForm d={d} initial={blank} errors={errors} busy={busy} submit={(f) => void add(f)} cancel={() => setAdding(false)} />}
      {d.plan.contributions.length === 0 && !adding && (
        <p className="rounded-xl border border-dashed border-hairline-2 px-3 py-4 text-center text-[13px] text-muted">
          Aucune série. Un versement qui revient se déclare une fois.
        </p>
      )}
      <ul className="space-y-2">
        {d.plan.contributions.map((c, i) => editing === i ? (
          <li key={i}>
            <SeriesForm d={d} initial={fieldsOf(c)} errors={errors} busy={busy} editing
                        submit={(f) => void save(i, f)} cancel={() => setEditing(null)} />
          </li>
        ) : (
          <li key={i} className="flex items-center gap-3 rounded-xl border border-hairline px-3 py-2.5 text-[13.5px]">
            <span className="grid size-8 shrink-0 place-items-center rounded-full" style={{ background: `color-mix(in srgb, ${NATURES[c.pocket]?.color ?? "var(--s1)"} 16%, transparent)` }}>
              <ArrowRight size={15} style={{ color: NATURES[c.pocket]?.color }} />
            </span>
            <button type="button" onClick={() => { setAdding(false); setEditing(i); }} disabled={busy}
                    className="min-w-0 flex-1 rounded-lg text-left transition hover:text-ink" title="Modifier cette série">
              <b className="num">{chf(c.amount, 0)} CHF</b> {c.every_label} vers {pocketName(c.pocket)}
              <span className="block text-[12px] text-muted">pendant {span(c.months)} · dès {c.start_label}</span>
            </button>
            <button type="button" aria-label="Modifier cette série" className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
                    onClick={() => { setAdding(false); setEditing(i); }}>
              <Pencil size={15} />
            </button>
            <button type="button" aria-label="Retirer cette série" className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-critical"
                    onClick={() => void remove(i)}>
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>
    </Block>
  );
}

/* ------------------------------------------------------------ suggestions */

function Suggestions({ d }: { d: Previsions }) {
  const { run } = useAction(d);
  return (
    <Block icon={<Sparkles size={16} />} title="Suggérés par l'historique"
           hint="une même catégorie a porté une grosse dépense au même mois, deux années de suite — confirmer la met dans le plan, ignorer la retire">
      {d.suggestions.length > 0 && (
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {d.suggestions.map((s) => <Suggestion key={`${s.category}-${s.month}`} s={s} run={run} />)}
        </div>
      )}
      {d.plan.ignored.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted">
          <span>Ignorées :</span>
          {d.plan.ignored.map((g) => (
            <button key={`${g.category}-${g.month}`} type="button" title="Restaurer la suggestion"
                    onClick={() => run({ action: "restore", category: g.category, month_no: g.month }, "Restaurée")}
                    className="inline-flex items-center gap-1 rounded-full border border-hairline-2 px-2 py-0.5 hover:bg-surface-2 hover:text-ink">
              <RotateCcw size={11} />{g.category} · {g.label}
            </button>
          ))}
        </div>
      )}
    </Block>
  );
}

function Suggestion({ s, run }: { s: Previsions["suggestions"][number]; run: (b: Record<string, unknown>, done?: string) => Promise<boolean> }) {
  const [label, setLabel] = useState(s.category);
  const [amount, setAmount] = useState(String(Math.round(s.amount)));
  return (
    <div className="flex flex-col rounded-xl border border-dashed border-hairline-2 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <b className="truncate text-[13.5px]">{s.category}</b>
        <span className="shrink-0 text-[12px] text-muted">chaque {s.month_label.toLowerCase()}</span>
      </div>
      <p className="mt-0.5 text-[12px] text-muted">~{chf(s.amount, 0)} CHF en {s.years.join(" et ")}</p>
      <div className="mt-2.5 grid grid-cols-[minmax(0,1fr)_6.5rem] gap-2">
        <Input value={label} onChange={(e) => setLabel(e.target.value)} aria-label={`Libellé de ${s.category}`} />
        <Input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label={`Montant de ${s.category}`} className="text-right" />
      </div>
      <div className="mt-2 flex gap-2">
        <Button size="sm" className="flex-1" onClick={() => run({ action: "add", month: s.target, seasonal: `${s.category}|${s.month}`, label, amount }, "Confirmé")}><Check size={14} />Confirmer</Button>
        <Button size="sm" variant="ghost" onClick={() => run({ action: "ignore", category: s.category, month_no: s.month }, "Ignoré")}><X size={14} />Ignorer</Button>
      </div>
    </div>
  );
}
