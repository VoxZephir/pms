/** Whole plans under a name: compared on one axis, then one card each --
 * created from any plan, renamed, copied, deleted with an undo, and the
 * one being edited always said where the plan is edited. */
import { Copy, MoreHorizontal, Pencil, Plus, Sparkles, SquarePen, Trash2 } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Lines, spreadTicks } from "@/charts/Lines";
import { Input } from "@/components/Form";
import { Sheet } from "@/components/Sheet";
import { Button, Chip, Dot, Note, Panel, cx } from "@/components/ui";
import { MONTHS_SHORT, chf, signedChf } from "@/lib/format";
import { NEW_SCENARIO_EVENT, planAction, type FieldErrors, type Previsions } from "@/lib/previsions";

type Plan = Previsions["comparison"][number];

const color = (slot: number | null) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");
const title = (p: Plan) => p.name ?? "Plan sans nom";
// Names to start from: a click fills the field, nothing more.
const IDEAS = ["Prudent", "Ambitieux", "Achat appartement", "Année sabbatique", "Nouveau job", "Enfant"];

function shortMonth(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
}

/** One edit of the plans, its toast, and the field errors when refused. */
function usePlans(d: Previsions) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const act = async (body: Record<string, unknown>, done?: string, opts?: { undo?: Record<string, unknown> }) => {
    setBusy(true);
    try {
      const r = await planAction(d.months, body);
      if (r.errors) { setErrors(r.errors); return false; }
      setErrors({});
      if (done) {
        const undo = opts?.undo;
        toast.success(done, undo ? {
          action: { label: "Annuler", onClick: () => void planAction(d.months, undo).then((x) => x.errors
            ? toast.error("Impossible de rétablir", { description: Object.values(x.errors)[0] })
            : toast("Rétabli")) },
        } : undefined);
      }
      return true;
    } catch (e) {
      toast.error("L'enregistrement a échoué", { description: (e as Error).message });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { errors, setErrors, busy, act };
}

const toPlan = () => document.getElementById("p-plan")?.scrollIntoView({ behavior: "smooth", block: "start" });

export function Scenarios({ d }: { d: Previsions }) {
  const c = d.comparison;
  const plans = usePlans(d);
  const [creating, setCreating] = useState<string | null>(null);   // the plan to start from
  const [renaming, setRenaming] = useState<Plan | null>(null);
  const labels = ["aujourd'hui", ...d.projection.rows.map((r) => r.label)];
  // The top bar's "Nouveau scénario…" opens the same sheet.
  useEffect(() => {
    const open = () => setCreating(d.active ?? "");
    window.addEventListener(NEW_SCENARIO_EVENT, open);
    return () => window.removeEventListener(NEW_SCENARIO_EVENT, open);
  }, [d.active]);
  const remove = (p: Plan) => plans.act({ action: "plan-delete", name: p.name },
    `Scénario « ${p.name} » supprimé`, { undo: { action: "plan-undelete" } });
  const show = (p: Plan) => plans.act({ action: "plan-switch", name: p.name }, `« ${title(p)} » affiché — la page le montre maintenant`);
  return (
    <Panel title="Scénarios"
           hint={c.length >= 2 ? `le cash de chaque plan sur ${d.horizon_label}, sur le même axe` : "garder un plan sous un nom, le copier, le varier — et comparer"}
           actions={<Button size="sm" variant="primary" onClick={() => setCreating(d.active ?? "")}><Plus size={14} />Nouveau scénario</Button>}>
      {c.length >= 2 && (
        <div className="mb-4">
          <Lines xs={labels.map((_, i) => i)} height={220}
                 series={c.map((s, i) => ({
                   key: String(i), name: title(s), color: color(s.slot),
                   width: s.active ? 2.75 : 1.75, values: [d.projection.cash, ...s.line],
                 }))}
                 tipFormat={(v) => `${chf(v, 0)} CHF`}
                 xLabel={(i) => labels[i]}
                 xTicks={(w) => spreadTicks(labels.length, w, (i) => (i === 0 ? "auj." : shortMonth(d.projection.rows[i - 1].key)), 70)}
                 markers={c.map((s, i) => {
                   const v = [d.projection.cash, ...s.line];
                   return { index: v.indexOf(Math.min(...v)), series: String(i), label: "" };
                 })}
                 zero={false} endLabels ariaLabel={`Cash projeté de ${c.length} scénarios`} />
        </div>
      )}
      {/* Cards scroll sideways on a phone, card by card; a grid from the tablet up. */}
      <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 no-scrollbar sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 xl:grid-cols-3">
        {c.map((s) => (
          <PlanCard key={s.name ?? "_"} s={s} d={d} busy={plans.busy}
                    onShow={() => show(s)} onCopy={() => setCreating(s.name ?? "")}
                    onRename={() => setRenaming(s)} onDelete={s.name ? () => remove(s) : undefined} />
        ))}
        <button type="button" onClick={() => setCreating(d.active ?? "")}
                className="group flex w-[82%] shrink-0 snap-center flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-hairline-2 p-5 text-center transition hover:border-ink-2 hover:bg-surface-2/40 sm:w-auto">
          <span className="grid size-10 place-items-center rounded-full bg-surface-2 text-ink-2 transition group-hover:bg-ink group-hover:text-surface"><Plus size={18} /></span>
          <span className="text-[14.5px] font-semibold">{c.length > 1 ? "Nouveau scénario" : "Créer un premier scénario"}</span>
          <span className="max-w-[16rem] text-[12.5px] text-muted">Une copie d'un plan, à varier : un loyer, un salaire, un gros achat — puis comparer.</span>
        </button>
      </div>
      <Note>Un scénario est un plan complet — revenu, dépense, ponctuels, versements, rendement. Le plan affiché est celui que « Le plan », plus bas, modifie ; en changer garde ce qui a été saisi.</Note>
      <CreateSheet d={d} from={creating} plans={plans} onClose={() => setCreating(null)} />
      <RenameSheet d={d} plan={renaming} plans={plans} onClose={() => setRenaming(null)} />
    </Panel>
  );
}

function PlanCard({ s, d, busy, onShow, onCopy, onRename, onDelete }: {
  s: Plan; d: Previsions; busy: boolean;
  onShow: () => void; onCopy: () => void; onRename: () => void; onDelete?: () => void;
}) {
  return (
    <div className={cx("relative flex w-[82%] shrink-0 snap-center flex-col rounded-2xl border p-4 transition sm:w-auto",
      s.active ? "border-transparent bg-surface-2/70 shadow-[inset_0_0_0_1.5px_var(--ink)]" : "border-hairline-2 hover:border-ink-2/60")}>
      <div className="flex items-center gap-2">
        <Dot color={color(s.slot)} />
        <h3 className={cx("min-w-0 flex-1 truncate text-[14.5px] font-semibold", !s.name && "italic")}>{title(s)}</h3>
        {s.active && <Chip tone="accent">affiché</Chip>}
        <Menu label={`Actions sur « ${title(s)} »`}>
          {!s.active && <Item icon={<SquarePen size={14} />} onSelect={onShow}>Afficher et modifier</Item>}
          {s.active && <Item icon={<SquarePen size={14} />} onSelect={toPlan}>Modifier le plan</Item>}
          <Item icon={<Copy size={14} />} onSelect={onCopy}>Dupliquer…</Item>
          <Item icon={<Pencil size={14} />} onSelect={onRename}>{s.name ? "Renommer…" : "Nommer…"}</Item>
          {onDelete && <Item icon={<Trash2 size={14} />} onSelect={onDelete} danger>Supprimer</Item>}
        </Menu>
      </div>
      <div className="mt-3 eyebrow">Point bas du cash</div>
      <div className={cx("num text-[22px] font-semibold tracking-tight", s.low.amount < 0 && "text-critical")}>
        {chf(s.low.amount, 0)} <span className="text-[12px] font-medium text-muted">CHF</span>
      </div>
      <div className="text-[12.5px] text-muted">
        {s.low.label}{s.low.amount < 0 && " · découvert"}
        {s.delta_low != null && Math.abs(s.delta_low) >= 1 && <> · <span className={cx("num", s.delta_low > 0 ? "text-good" : "text-critical")}>{signedChf(s.delta_low)}</span> vs affiché</>}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
        <dt className="text-muted">Revenu / mois</dt><dd className="num text-right">{chf(s.income, 0)}</dd>
        <dt className="text-muted">Dépense / mois</dt><dd className="num text-right">{chf(s.spend, 0)}{s.spend_source === "history" && <span className="text-muted"> hist.</span>}</dd>
        <dt className="text-muted">Placé</dt><dd className="num text-right">{chf(s.moved, 0)}</dd>
        <dt className="text-muted">Cash à {d.horizon_label}</dt><dd className="num text-right">{chf(s.end, 0)}</dd>
        {s.wealth != null && <><dt className="text-muted">Patrimoine</dt><dd className="num text-right font-medium">{chf(s.wealth, 0)}
          {s.delta_wealth != null && Math.abs(s.delta_wealth) >= 1 && <span className={cx("ml-1 text-[11.5px]", s.delta_wealth > 0 ? "text-good" : "text-critical")}>{signedChf(s.delta_wealth)}</span>}</dd></>}
      </dl>
      <div className="mt-auto pt-3">
        {s.active
          ? <Button size="sm" className="w-full" onClick={toPlan}><SquarePen size={14} />Modifier ce plan</Button>
          : <Button size="sm" className="w-full" disabled={busy} onClick={onShow}>Afficher</Button>}
      </div>
    </div>
  );
}

function Menu({ label, children }: { label: string; children: ReactNode }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" aria-label={label} className="rounded-lg p-1.5 text-muted transition hover:bg-surface-2 hover:text-ink">
          <MoreHorizontal size={16} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6}
                              className="z-50 min-w-[12rem] rounded-xl border border-hairline bg-surface p-1 shadow-pop data-[state=open]:animate-[pop-in_.14s_ease-out]">
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function Item({ icon, children, onSelect, danger }: { icon: ReactNode; children: ReactNode; onSelect: () => void; danger?: boolean }) {
  return (
    <DropdownMenu.Item onSelect={onSelect}
                       className={cx("flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] outline-none data-[highlighted]:bg-surface-2",
                         danger ? "text-critical" : "text-ink")}>
      <span className={danger ? "" : "text-muted"}>{icon}</span>{children}
    </DropdownMenu.Item>
  );
}

/** The name of a new plan and which plan it starts from. */
function CreateSheet({ d, from, plans, onClose }: {
  d: Previsions; from: string | null; plans: ReturnType<typeof usePlans>; onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (from != null) { setName(""); setBase(from); plans.setErrors({}); }
  }, [from]); // eslint-disable-line react-hooks/exhaustive-deps
  const taken = d.comparison.some((p) => p.name === name.trim());
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (await plans.act({ action: "plan-save-as", name: n, from: base }, `« ${n} » créé — c'est lui que tu modifies maintenant`)) {
      onClose();
      setTimeout(toPlan, 250);
    }
  };
  const error = plans.errors["plan-new"] ?? (taken ? "Un scénario porte déjà ce nom." : undefined);
  return (
    <Sheet open={from != null} onOpenChange={(o) => !o && onClose()} title="Nouveau scénario"
           description="Une copie complète d'un plan, sous un nom. Ensuite, on le modifie dans « Le plan » sans toucher à l'original.">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="scenario-name" className="text-[12.5px] font-medium text-ink-2">Nom</label>
          <Input id="scenario-name" ref={input} autoFocus value={name} maxLength={60} className="mt-1.5"
                 placeholder="Ex. Achat appartement" invalid={!!error} aria-describedby="scenario-name-note"
                 onChange={(e) => { setName(e.target.value); plans.setErrors({}); }} />
          <p id="scenario-name-note" role={error ? "alert" : undefined} className={cx("mt-1.5 text-[12px]", error ? "text-critical" : "text-muted")}>
            {error ?? "Ce qu'il change, en deux ou trois mots."}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {IDEAS.filter((x) => !d.comparison.some((p) => p.name === x)).map((x) => (
              <button key={x} type="button" onClick={() => { setName(x); input.current?.focus(); }}
                      className={cx("rounded-full border px-2.5 py-1 text-[12.5px] transition",
                        name === x ? "border-ink bg-surface-2 font-medium" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>{x}</button>
            ))}
          </div>
        </div>
        <fieldset>
          <legend className="text-[12.5px] font-medium text-ink-2">Partir de</legend>
          <div className="mt-1.5 space-y-1.5" role="radiogroup">
            {d.comparison.map((p) => {
              const id = p.name ?? "";
              const on = base === id;
              return (
                <button key={id || "_"} type="button" role="radio" aria-checked={on} onClick={() => setBase(id)}
                        className={cx("flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left text-[13.5px] transition",
                          on ? "border-ink bg-surface-2" : "border-hairline-2 hover:bg-surface-2")}>
                  <span className={cx("grid size-4 shrink-0 place-items-center rounded-full border", on ? "border-ink" : "border-hairline-2")}>
                    {on && <span className="size-2 rounded-full bg-ink" />}
                  </span>
                  <Dot color={color(p.slot)} />
                  <span className={cx("min-w-0 flex-1 truncate", !p.name && "italic")}>{title(p)}</span>
                  <span className="num shrink-0 text-[12px] text-muted">{chf(p.income, 0)} / {chf(p.spend, 0)}</span>
                  {p.active && <Chip>affiché</Chip>}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[12px] text-muted">revenu / dépense par mois de chacun · le plan affiché garde ce qui y a été saisi</p>
        </fieldset>
        <p className="inline-flex items-center gap-1.5 text-[12px] text-muted"><Sparkles size={13} />Ou décrire une variante en une phrase : « Scénario en mots », sous les scénarios.</p>
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || taken || plans.busy}>Créer et modifier</Button>
        </div>
      </form>
    </Sheet>
  );
}

function RenameSheet({ d, plan, plans, onClose }: {
  d: Previsions; plan: Plan | null; plans: ReturnType<typeof usePlans>; onClose: () => void;
}) {
  const [name, setName] = useState("");
  useEffect(() => { if (plan) { setName(plan.name ?? ""); plans.setErrors({}); } }, [plan]); // eslint-disable-line react-hooks/exhaustive-deps
  const taken = d.comparison.some((p) => p.name === name.trim() && p.name !== plan?.name);
  const error = plans.errors["plan-rename"] ?? (taken ? "Un scénario porte déjà ce nom." : undefined);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (await plans.act({ action: "plan-rename", old: plan?.name ?? "", name: n }, plan?.name ? `Renommé en « ${n} »` : `Plan enregistré sous « ${n} »`)) onClose();
  };
  return (
    <Sheet open={plan != null} onOpenChange={(o) => !o && onClose()} title={plan?.name ? `Renommer « ${plan.name} »` : "Nommer ce plan"}
           description={plan?.name ? undefined : "Le plan affiché, gardé sous un nom : il devient un scénario à comparer."}>
      <form onSubmit={submit} className="space-y-3">
        <Input autoFocus value={name} maxLength={60} aria-label="Nouveau nom" invalid={!!error}
               onChange={(e) => { setName(e.target.value); plans.setErrors({}); }} onFocus={(e) => e.target.select()} />
        {error && <p role="alert" className="text-[12px] text-critical">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || taken || plans.busy}>{plan?.name ? "Renommer" : "Enregistrer"}</Button>
        </div>
      </form>
    </Sheet>
  );
}

/** At the top of "Le plan": which plan the fields below edit, and the way
 * to another one, without scrolling back up. */
export function PlanHeader({ d }: { d: Previsions }) {
  const plans = usePlans(d);
  const [renaming, setRenaming] = useState<Plan | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const shown = d.comparison.find((p) => p.active) ?? d.comparison[0];
  const others = d.comparison.filter((p) => !p.active && p.name);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-hairline bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <h2 className="text-[17px] font-semibold tracking-tight">Le plan</h2>
        <p data-plan-shown="" className="flex min-w-0 items-center gap-1.5 text-[13px] text-ink-2">
          Tu modifies <Dot color={color(shown?.slot ?? null)} />
          <b className={cx("truncate", !shown?.name && "italic font-medium")}>{shown ? title(shown) : "Plan sans nom"}</b>
          <span className="hidden text-muted sm:inline">· les autres scénarios ne bougent pas</span>
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {others.length > 0 && (
          <select aria-label="Modifier un autre scénario" value="" disabled={plans.busy}
                  onChange={(e) => { const p = others.find((x) => x.name === e.target.value); if (p) void plans.act({ action: "plan-switch", name: p.name }, `« ${p.name} » affiché`); }}
                  className="h-9 rounded-xl border border-hairline-2 bg-surface px-2.5 text-[13px]">
            <option value="">Passer à…</option>
            {others.map((p) => <option key={p.name!} value={p.name!}>{p.name}</option>)}
          </select>
        )}
        {shown && <Button size="sm" onClick={() => setRenaming(shown)}><Pencil size={14} />{shown.name ? "Renommer" : "Nommer"}</Button>}
        <Button size="sm" onClick={() => setCreating(d.active ?? "")}><Copy size={14} />Dupliquer</Button>
      </div>
      <CreateSheet d={d} from={creating} plans={plans} onClose={() => setCreating(null)} />
      <RenameSheet d={d} plan={renaming} plans={plans} onClose={() => setRenaming(null)} />
    </div>
  );
}
