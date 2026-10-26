/** The corrections in place, the personal rules, the merges. Corrections live
 * outside the statement (data/overrides.json): the ledger stays a faithful
 * copy of what the bank printed. */
import { ChevronRight, GitMerge, Pencil, Search, Sparkles, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { AiStatusNote, MerchantAssist, useAi } from "@/components/Assist";
import { Field, Input, Select } from "@/components/Form";
import { PageHeader } from "@/components/PageState";
import { Sheet } from "@/components/Sheet";
import { Button, ButtonLink, Callout, Card, Chip, Note, Panel, Segmented, Skeleton, cx } from "@/components/ui";
import { ApiError, send, useApi } from "@/lib/api";
import { bucketLabel, chf, frDate } from "@/lib/format";
import type { Choices } from "@/lib/types";

interface Entry {
  kind: "rule" | "pin" | "alias";
  match: string; mode?: string; key?: string; pattern?: boolean; canonical?: string;
  category: string; subcategory: string; bucket: string;
  count: number; amount: number; at: string; date?: string;
}
interface Coverage {
  lines: number; lines_done: number; share_lines: number; share_amount: number;
  twint: number; twint_amount: number; unknown: number; unknown_amount: number; unknown_payees: number;
}
interface MergeHint { prefix: string; canonical: string; category: string; labels: string[]; count: number; amount: number }
interface Corrections {
  entries: Entry[]; total: number; touched: number; twint_left: number;
  coverage: Coverage; merges: MergeHint[]; counts: { rules: number; pins: number; merges: number };
  local_rules: { pattern: string; category: string; subcategory: string }[];
  choices: Choices; counterparties: string[];
}

/** One write to the corrections; its toast offers the undo the server
 * answered with (a delete, an edit, a merge). Null when it went through,
 * the field errors when refused. */
async function act(body: Record<string, unknown>, done: string): Promise<Record<string, string> | null> {
  try {
    const r = await send<{ undo?: Record<string, unknown> | null }>("/api/corrections", body);
    const undo = r.undo;
    toast.success(done, undo ? {
      action: { label: "Annuler", onClick: async () => { await send("/api/corrections", undo); toast("Annulé"); } },
    } : undefined);
    return null;
  } catch (e) {
    if (e instanceof ApiError && e.data && typeof e.data === "object" && "errors" in e.data) {
      return (e.data as { errors: Record<string, string> }).errors;
    }
    toast.error("L'enregistrement a échoué", { description: (e as Error).message });
    return {};
  }
}

const GROUPS = [
  { kind: "rule", title: "Règles par bénéficiaire", hint: "attrapent aussi les paiements futurs" },
  { kind: "pin", title: "Épingles", hint: "un seul mouvement chacune ; l'emportent sur la règle" },
  { kind: "alias", title: "Fusions", hint: "plusieurs orthographes, un seul bénéficiaire" },
] as const;

export default function CorrectionsPage() {
  const { data, isPending, error } = useApi<Corrections>("/api/corrections");
  const ai = useAi();
  if (error) return <Callout tone="bad" title="Les corrections n'ont pas pu être chargées">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-72 rounded-card" /></div>;
  return (
    <>
      <PageHeader title="Corrections"
                  subtitle={`${data.total} correction${data.total > 1 ? "s" : ""} · ${data.touched} mouvement${data.touched > 1 ? "s" : ""} affecté${data.touched > 1 ? "s" : ""}`} />
      <div className="space-y-4 sm:space-y-5">
        <CoverageCard c={data.coverage} counts={data.counts} />
        <MerchantAssist choices={data.choices} />
        <MergeHints merges={data.merges} />
        <InPlace entries={data.entries} choices={data.choices} />
        <LocalRules data={data} />
        <Merges data={data} />
        <AiStatusNote status={ai} />
        <Note className="px-1">
          Les corrections vivent dans <code>data/overrides.json</code>, séparé du ledger. Une épingle est indexée sur
          (référence, devise), la même identité que le ledger utilise pour dédoublonner : elle survit à la réimportation.
        </Note>
      </div>
    </>
  );
}

const ORDERS = [
  { id: "recent", label: "Récentes" },
  { id: "impact", label: "Impact" },
  { id: "name", label: "A → Z" },
] as const;

function InPlace({ entries, choices }: { entries: Entry[]; choices: Choices }) {
  const [q, setQ] = useState("");
  const [order, setOrder] = useState<(typeof ORDERS)[number]["id"]>("recent");
  const [editing, setEditing] = useState<Entry | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const fold = (s: string) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
  const shown = useMemo(() => {
    const words = fold(q).split(/\s+/).filter(Boolean);
    const hit = words.length ? entries.filter((e) => {
      const hay = fold([e.match, e.category, e.subcategory, e.bucket, e.canonical ?? ""].join(" "));
      return words.every((w) => hay.includes(w));
    }) : entries;
    const sorted = [...hit];
    if (order === "impact") sorted.sort((a, b) => b.amount - a.amount);
    else if (order === "name") sorted.sort((a, b) => a.match.localeCompare(b.match, "fr"));
    else sorted.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
    return sorted;
  }, [entries, q, order]);
  if (!entries.length) {
    return (
      <Panel title="Corrections en place">
        <p className="text-[14px] text-muted">Aucune correction pour l'instant. Ouvrez une transaction pour la reclasser — cette ligne, ou tout son bénéficiaire.</p>
      </Panel>
    );
  }
  return (
    <Panel title="Corrections en place" hint={`${entries.length} en tout · une correction se modifie ou se retire, et s'annule depuis son message`}
           actions={<Segmented size="sm" label="Ordre" value={order} onChange={setOrder} options={[...ORDERS]} />}>
      <label className="relative mb-3 block">
        <span className="sr-only">Chercher une correction</span>
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chercher un bénéficiaire, une catégorie…"
               autoCapitalize="off" autoCorrect="off" spellCheck={false}
               className="h-11 w-full rounded-xl border border-hairline-2 bg-surface pl-9 pr-3 text-[16px] outline-none focus:border-accent sm:h-10 sm:text-[14px]" />
      </label>
      <div className="space-y-2">
        {GROUPS.map((g) => {
          const rows = shown.filter((e) => e.kind === g.kind);
          if (!rows.length) return null;
          const isOpen = open.has(g.kind) || !!q || rows.length <= 8;
          return (
            <div key={g.kind} className="overflow-hidden rounded-2xl border border-hairline">
              <button type="button" aria-expanded={isOpen}
                      onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(g.kind)) n.delete(g.kind); else n.add(g.kind); return n; })}
                      className="flex w-full items-center gap-2 bg-surface-2/50 px-3 py-2.5 text-left">
                <ChevronRight size={15} className={cx("text-muted transition-transform", isOpen && "rotate-90")} />
                <b className="text-[14px]">{g.title}</b><span className="num text-[13px] text-muted">({rows.length})</span>
                <span className="ml-auto hidden text-[12px] text-muted sm:block">{g.hint}</span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.ul initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="divide-y divide-hairline overflow-hidden">
                    {rows.map((e) => <EntryRow key={`${e.kind}-${e.match}-${e.key ?? ""}-${e.mode ?? ""}`} e={e} onEdit={() => setEditing(e)} />)}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>
          );
        })}
        {shown.length === 0 && <p className="py-4 text-center text-[13.5px] text-muted">Aucune correction ne correspond.</p>}
      </div>
      <EditSheet entry={editing} choices={choices} onClose={() => setEditing(null)} />
    </Panel>
  );
}

function EntryRow({ e, onEdit }: { e: Entry; onEdit: () => void }) {
  const remove = () => act({ action: "delete", kind: e.kind, match: e.match, mode: e.mode, key: e.key }, "Correction retirée");
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-3 py-2.5 text-[13.5px] sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_90px_100px_auto]">
      <div className="min-w-0">
        <div className="truncate font-medium">{e.match}</div>
        <div className="truncate text-[12px] text-muted">
          {e.kind === "alias" && e.pattern ? "tous les bénéficiaires de ce motif"
            : e.kind === "rule" && e.mode === "contains" ? "tout bénéficiaire contenant ce texte"
            : e.kind === "pin" ? (e.date ? frDate(e.date) : "mouvement absent du ledger")
            : `posée le ${frDate(e.at)}`}
        </div>
      </div>
      <span className="row-span-2 flex items-center sm:order-last sm:row-span-1">
        {e.kind !== "alias" && (
          <button type="button" onClick={onEdit} aria-label={`Modifier la correction « ${e.match} »`}
                  className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-ink"><Pencil size={15} /></button>
        )}
        <button type="button" onClick={remove} aria-label={`Retirer la correction « ${e.match} »`}
                className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-critical"><Trash2 size={15} /></button>
      </span>
      <span className="flex min-w-0 flex-wrap gap-1">
        {e.canonical && <Chip>{e.canonical}</Chip>}
        {e.category && <Chip tone="accent">{e.category}</Chip>}
        {e.subcategory && <span className="text-[12px] text-muted">{e.subcategory}</span>}
        {e.bucket && <Chip>{bucketLabel(e.bucket)}</Chip>}
      </span>
      <span className={cx("num hidden text-right sm:block", !e.count && "text-muted")}>{e.count}×</span>
      <span className="num hidden text-right sm:block">{chf(e.amount)}</span>
    </li>
  );
}

function LocalRules({ data }: { data: Corrections }) {
  const [f, setF] = useState({ pattern: "", category: "", subcategory: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const add = async (e: FormEvent) => {
    e.preventDefault();
    const errs = await act({ action: "lr-add", ...f }, "Règle ajoutée");
    if (errs) setErrors(errs);
    else { setErrors({}); setF({ pattern: "", category: "", subcategory: "" }); }
  };
  return (
    <Panel title="Règles personnelles" hint="data/local_rules.json — hors du dépôt, comme les relevés">
      <p className="mb-3 text-[13px] text-ink-2">Des règles qui nomment un employeur, une régie, un praticien ou une personne. Elles s'appliquent avant les règles publiques et l'emportent sur elles.</p>
      <form onSubmit={add} className="grid gap-3 sm:grid-cols-[1.4fr_1fr_1fr_auto] sm:items-start">
        <Field label="Motif" error={errors["lr-pattern"]} hint="une alternative : Coop|Migros · sans tenir compte de la casse">
          {(id, by) => <Input id={id} aria-describedby={by} required value={f.pattern} onChange={(e) => setF({ ...f, pattern: e.target.value })} invalid={!!errors["lr-pattern"]} />}
        </Field>
        <Field label="Catégorie" error={errors["lr-category"]}>
          {(id) => <Select id={id} required value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} invalid={!!errors["lr-category"]}>
            <option value="">— choisir —</option>
            {data.choices.categories.map((c) => <option key={c}>{c}</option>)}
          </Select>}
        </Field>
        <Field label="Sous-catégorie">
          {(id) => <Input id={id} value={f.subcategory} onChange={(e) => setF({ ...f, subcategory: e.target.value })} />}
        </Field>
        <Button type="submit" variant="primary" className="sm:mt-[25px]">Ajouter</Button>
      </form>
      {data.local_rules.length > 0 ? (
        <ul className="mt-4 divide-y divide-hairline border-t border-hairline">
          {data.local_rules.map((r) => (
            <li key={`${r.pattern}-${r.category}-${r.subcategory}`} className="flex items-center gap-3 py-2.5 text-[13.5px]">
              <code className="min-w-0 flex-1 truncate rounded-md bg-surface-2 px-1.5 py-0.5 text-[12.5px]">{r.pattern}</code>
              <Chip tone="accent">{r.category}</Chip>
              {r.subcategory && <span className="hidden text-[12px] text-muted sm:inline">{r.subcategory}</span>}
              <button type="button" aria-label={`Retirer la règle ${r.pattern}`} className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-critical"
                      onClick={() => act({ action: "lr-delete", ...r }, "Règle retirée")}><Trash2 size={15} /></button>
            </li>
          ))}
        </ul>
      ) : <p className="mt-3 text-[13px] text-muted">Aucune règle personnelle : la catégorisation tient sur les règles publiques.</p>}
    </Panel>
  );
}

function Merges({ data }: { data: Corrections }) {
  const [variant, setVariant] = useState("");
  const [canonical, setCanonical] = useState("");
  const [prefix, setPrefix] = useState("");
  const [chain, setChain] = useState("");
  const listId = "counterparties";
  return (
    <Panel title="Fusionner deux bénéficiaires" hint="quand la banque écrit le même nom de deux façons">
      <datalist id={listId}>{data.counterparties.map((c) => <option key={c} value={c} />)}</datalist>
      <form className="grid gap-3 sm:grid-cols-[1fr_auto_1fr_auto] sm:items-end"
            onSubmit={async (e) => { e.preventDefault(); if (!(await act({ action: "merge", variant, canonical }, `${variant} → ${canonical}`))) { setVariant(""); setCanonical(""); } }}>
        <Field label="Bénéficiaire à fusionner">{(id) => <Input id={id} list={listId} required value={variant} onChange={(e) => setVariant(e.target.value)} autoComplete="off" />}</Field>
        <span className="hidden pb-2.5 text-[13px] text-muted sm:block">devient</span>
        <Field label="Nom à conserver">{(id) => <Input id={id} list={listId} required value={canonical} onChange={(e) => setCanonical(e.target.value)} autoComplete="off" />}</Field>
        <Button type="submit" variant="primary">Fusionner</Button>
      </form>
      <div className="mt-5 border-t border-hairline pt-4">
        <h3 className="text-[14px] font-semibold">Toute une enseigne</h3>
        <p className="mt-0.5 text-[12.5px] text-muted">Une succursale par caisse : toutes les orthographes d'une chaîne, et celles à venir.</p>
        <form className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto_1fr_auto] sm:items-end"
              onSubmit={async (e) => { e.preventDefault(); if (!(await act({ action: "merge", prefix, canonical: chain }, `Tout ce qui commence par « ${prefix} » → ${chain}`))) { setPrefix(""); setChain(""); } }}>
          <Field label="Tout ce qui commence par">{(id) => <Input id={id} required placeholder="Coop" value={prefix} onChange={(e) => setPrefix(e.target.value)} />}</Field>
          <span className="hidden pb-2.5 text-[13px] text-muted sm:block">devient</span>
          <Field label="Nom à conserver">{(id) => <Input id={id} required placeholder="Coop" value={chain} onChange={(e) => setChain(e.target.value)} />}</Field>
          <Button type="submit" variant="primary">Fusionner l'enseigne</Button>
        </form>
      </div>
      <Note>Les noms fusionnés comptent ensuite comme un seul dans les totaux, les classements et les règles. Les catégories sont déterminées avant la fusion : une station-service Coop reste en transport.</Note>
      <p className="mt-2 text-[12.5px]"><Link to="/transactions" className="text-accent">Reclasser depuis les transactions →</Link></p>
    </Panel>
  );
}

/* ------------------------------------------------------------- coverage */

/** How much of the spending a category explains, and where the rest is:
 * the Twints without a payee, the payees no rule knows. */
function CoverageCard({ c, counts }: { c: Coverage; counts: Corrections["counts"] }) {
  const done = c.twint === 0 && c.unknown === 0;
  return (
    <Card className="p-5" data-coverage>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="eyebrow">Classement</div>
        <div className="text-[12.5px] text-muted">
          {counts.rules} règle{counts.rules > 1 ? "s" : ""} · {counts.pins} épingle{counts.pins > 1 ? "s" : ""} · {counts.merges} fusion{counts.merges > 1 ? "s" : ""}
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3">
        <span className="num text-[30px] font-semibold leading-none tracking-[-0.03em]">{Math.floor(c.share_amount)} %</span>
        <span className="text-[13px] text-ink-2">des francs dépensés ont une catégorie · {Math.floor(c.share_lines)} % des paiements ({c.lines_done} sur {c.lines})</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${Math.floor(c.share_amount)} % classé`}>
        <div className="h-full rounded-full bg-good" style={{ width: `${c.share_amount}%` }} />
      </div>
      {done ? <p className="mt-3 text-[13px] text-good">Tout est classé.</p> : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {c.twint > 0 && (
            <div className="flex items-center gap-3 rounded-2xl bg-surface-2/60 p-3">
              <Sparkles size={18} className="shrink-0 text-accent" />
              <div className="min-w-0 flex-1 text-[13px]">
                <b>{c.twint} Twint à identifier</b>
                <div className="text-muted">{chf(c.twint_amount, 0)} CHF · le relevé n'en imprime que le montant</div>
              </div>
              <ButtonLink to="/corrections/tri" variant="primary" size="sm">Trier</ButtonLink>
            </div>
          )}
          {c.unknown > 0 && (
            <div className="flex items-center gap-3 rounded-2xl bg-surface-2/60 p-3">
              <Search size={18} className="shrink-0 text-muted" />
              <div className="min-w-0 flex-1 text-[13px]">
                <b>{c.unknown} paiement{c.unknown > 1 ? "s" : ""} non catégorisé{c.unknown > 1 ? "s" : ""}</b>
                <div className="text-muted">{chf(c.unknown_amount, 0)} CHF · {c.unknown_payees} bénéficiaire{c.unknown_payees > 1 ? "s" : ""}</div>
              </div>
              <ButtonLink to="/transactions?preset=all&todo=1" size="sm">Voir</ButtonLink>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/* --------------------------------------------------------- merge hints */

/** Payees the bank spells several ways, that one merge would gather. Shown
 * with every spelling, so the merge is judged before it is made. */
function MergeHints({ merges }: { merges: MergeHint[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!merges.length) return null;
  const merge = async (m: MergeHint) => {
    setBusy(m.prefix);
    await act({ action: "merge", prefix: m.prefix, canonical: m.canonical }, `${m.labels.length} orthographes → ${m.canonical}`);
    setBusy(null);
  };
  return (
    <Panel id="p-merge-hints" title="Fusions proposées" hint="un même début de nom, une même catégorie : sans doute une seule enseigne">
      <ul className="grid gap-3 md:grid-cols-2">
        {merges.map((m) => (
          <li key={m.prefix} className="flex min-w-0 flex-col rounded-2xl border border-hairline p-3">
            <div className="flex items-baseline gap-2">
              <b className="min-w-0 flex-1 truncate text-[14px]">{m.canonical}</b>
              <span className="num shrink-0 text-[12.5px] text-muted">{m.count}× · {chf(m.amount, 0)} CHF</span>
            </div>
            <div className="mt-0.5 text-[12px] text-muted">{m.labels.length} orthographes · {m.category}</div>
            <ul className="mt-2 flex flex-wrap gap-1">
              {m.labels.slice(0, 6).map((l) => <li key={l}><Chip>{l}</Chip></li>)}
              {m.labels.length > 6 && <li className="text-[12px] text-muted">+{m.labels.length - 6}</li>}
            </ul>
            <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-3">
              <Button size="sm" onClick={() => merge(m)} disabled={busy === m.prefix} title={`Tout ce qui commence par « ${m.prefix} » devient « ${m.canonical} »`}>
                <GitMerge size={14} />Fusionner
              </Button>
              <span className="min-w-0 text-[12px] text-muted">tout ce qui commence par « {m.prefix} »</span>
            </div>
          </li>
        ))}
      </ul>
      <Note>Une fusion attrape aussi les orthographes à venir. Les catégories restent celles d'avant la fusion, et la fusion s'annule depuis son message ou se retire plus bas.</Note>
    </Panel>
  );
}

/* ---------------------------------------------------------------- edit */

/** A rule or a pin given another category or bucket, in place: its reach
 * is kept, and the toast undoes it. */
function EditSheet({ entry, choices, onClose }: { entry: Entry | null; choices: Choices; onClose: () => void }) {
  const [f, setF] = useState({ category: "", subcategory: "", bucket: "" });
  const [error, setError] = useState("");
  const [shown, setShown] = useState<Entry | null>(null);
  if (entry !== shown) {
    setShown(entry);
    setF({ category: entry?.category ?? "", subcategory: entry?.subcategory ?? "", bucket: entry?.bucket ?? "" });
    setError("");
  }
  const save = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!entry) return;
    const errs = await act({ action: "edit", kind: entry.kind, match: entry.match, mode: entry.mode, key: entry.key, ...f },
                           `${entry.match} → ${f.category || bucketLabel(f.bucket)}`);
    if (errs) setError(Object.values(errs)[0] ?? "");
    else onClose();
  };
  const subs = choices.subcategories[f.category] ?? [];
  return (
    <Sheet open={!!entry} onOpenChange={(o) => !o && onClose()} title={entry ? `Modifier « ${entry.match} »` : ""}
           description={entry?.kind === "rule" ? "La règle garde sa portée : les paiements passés et futurs de ce bénéficiaire." : "Ce seul mouvement."}>
      <form onSubmit={save} className="space-y-4">
        <Field label="Catégorie">
          {(id) => <Select id={id} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value, subcategory: "" })}>
            <option value="">— inchangée par la correction —</option>
            {choices.categories.map((c) => <option key={c}>{c}</option>)}
          </Select>}
        </Field>
        <Field label="Sous-catégorie">
          {(id) => subs.length ? (
            <Select id={id} value={f.subcategory} onChange={(e) => setF({ ...f, subcategory: e.target.value })}>
              <option value="">—</option>
              {subs.map((c) => <option key={c}>{c}</option>)}
            </Select>
          ) : <Input id={id} value={f.subcategory} onChange={(e) => setF({ ...f, subcategory: e.target.value })} />}
        </Field>
        <Field label="Besoin ou envie">
          {(id) => <Select id={id} value={f.bucket} onChange={(e) => setF({ ...f, bucket: e.target.value })}>
            <option value="">— selon la catégorie —</option>
            {choices.buckets.map((b) => <option key={b} value={b}>{bucketLabel(b)}</option>)}
          </Select>}
        </Field>
        {error && <p role="alert" className="text-[13px] text-critical">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" disabled={!f.category && !f.bucket}>Enregistrer</Button>
      </form>
    </Sheet>
  );
}
