/** B: categories proposed for the payees no rule recognises. */
import { Search, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, Select } from "@/components/Form";
import { Button, Chip, Dot, Note, Panel } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, frDate } from "@/lib/format";
import type { Choices } from "@/lib/types";
import { type AiStatus, AiBadge, failed } from "./common";

interface Payee {
  label: string; kind: string; location: string; count: number; total: number;
  median: number; last: string; key: string;
  /** Where the card was used that day, for a payment printed without a place. */
  near?: string;
  suggestion: {
    category: string | null; subcategory: string; confidence: string; why: string; slot?: number | null;
    /** DeepSeek: pages its search returned (absent: no search was made). */
    searched?: number; pages?: { titre: string; url: string }[];
  } | null;
}
interface Merchants { ai: AiStatus; payees: Payee[]; private: number; pending: number }

export function MerchantAssist({ choices }: { choices: Choices }) {
  const { data } = useApi<Merchants>("/api/ai/merchants");
  const [busy, setBusy] = useState(false);
  if (!data || (!data.payees.length && !data.private)) return null;
  const suggest = async () => {
    setBusy(true);
    try {
      await send("/api/ai/merchants", {});
    } catch (e) {
      failed("Les suggestions n'ont pas pu être obtenues", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title={<span className="flex flex-wrap items-center gap-2">Bénéficiaires non classés {data.payees.some((p) => p.suggestion?.category) && <AiBadge>suggestions</AiBadge>}</span>}
           hint="aucune règle ne les reconnaît ; une catégorie acceptée devient une règle, qui classe aussi les suivants"
           actions={data.ai.enabled && data.pending > 0
             ? <Button size="sm" onClick={suggest} disabled={busy}><Sparkles size={14} />{busy ? "Recherche…" : "Proposer des catégories"}</Button>
             : undefined}>
      {data.payees.length > 0 ? (
        <ul className="divide-y divide-hairline">
          {data.payees.map((p) => <PayeeRow key={p.label} p={p} choices={choices} />)}
        </ul>
      ) : <p className="text-[13px] text-muted">Aucun commerçant à classer.</p>}
      {data.private > 0 && (
        <Note>
          {data.private} bénéficiaire{data.private > 1 ? "s" : ""} à nom de personne {data.private > 1 ? "restent" : "reste"} hors
          de la liste : un nom de personne ne dit rien au modèle, et ne sort pas de l'app. Ils se classent depuis la table.
        </Note>
      )}
    </Panel>
  );
}

function PayeeRow({ p, choices }: { p: Payee; choices: Choices }) {
  const s = p.suggestion;
  const [other, setOther] = useState(false);
  const [category, setCategory] = useState(s?.category ?? "");
  const [busy, setBusy] = useState(false);
  const apply = async (cat: string, sub = "") => {
    setBusy(true);
    try {
      const r = await send<{ count: number; undo: unknown }>("/api/reclassify",
        { key: p.key, scope: "merchant", category: cat, subcategory: sub });
      toast.success(`${p.label} → ${cat}`, {
        description: `Règle enregistrée : ${r.count} mouvement${r.count > 1 ? "s" : ""}, et les prochains.`,
        action: { label: "Annuler", onClick: async () => { await send("/api/reclassify/undo", r.undo); toast("Correction annulée"); } },
      });
    } catch (e) {
      failed("Le classement a échoué", e);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); if (category) void apply(category); };
  // Asked again past the caches -- with a web search where the provider has one.
  const retry = async () => {
    setBusy(true);
    try {
      const r = await send<Merchants>("/api/ai/merchants", { retry: [p.label] });
      const now = r.payees.find((x) => x.label === p.label)?.suggestion;
      if (now?.category) toast.success(`${p.label} → ${now.category}`, { description: now.why || undefined });
      else toast(`${p.label} : toujours pas de suggestion`, { description: searchNote(now) });
    } catch (e) {
      failed("La suggestion n'a pas pu être obtenue", e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="min-w-0 truncate font-medium">{p.label}</span>
        <span className="num text-[13px] text-ink-2">{p.count} × · {chf(p.total)} CHF</span>
      </div>
      <div className="text-[12px] text-muted">
        {[frDate(p.last), p.location || (p.near && `sans lieu imprimé, carte utilisée à ${p.near} ce jour-là`), p.kind].filter(Boolean).join(" · ")}
      </div>
      {s && (s.category ? (
        <div className="mt-2 rounded-xl bg-[color-mix(in_srgb,var(--s6)_8%,transparent)] px-3 py-2 text-[13px]">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Dot color={s.slot != null ? `var(--s${s.slot})` : "var(--unsorted)"} />
            <b>{s.category}</b>{s.subcategory && <span className="text-ink-2">· {s.subcategory}</span>}
            <span className="text-muted">· règle « {p.label} »</span>
            <Chip tone={s.confidence === "haute" ? "good" : s.confidence === "moyenne" ? "warn" : "neutral"}>{s.confidence}</Chip>
          </div>
          {s.why && <div className="mt-0.5 text-ink-2">{s.why}</div>}
          <Pages s={s} />
        </div>
      ) : (
        <div className="mt-2 text-[13px] text-muted">
          {s.why && <p className="text-ink-2">{sentence(s.why)}</p>}
          <p>{searchNote(s)}</p>
          <Pages s={s} />
        </div>
      ))}
      <div className="mt-2 flex flex-wrap gap-2">
        {s?.category && <Button size="sm" disabled={busy} onClick={() => apply(s.category!, s.subcategory)}>Accepter</Button>}
        {s && !s.category && (
          <Button size="sm" disabled={busy} onClick={retry}><Sparkles size={14} />{busy ? "Recherche…" : "Redemander"}</Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setOther((v) => !v)} aria-expanded={other}>Autre catégorie</Button>
        {/* The owner's own browser searches, not the app: nothing is sent from here. */}
        <a href={`https://duckduckgo.com/?q=${encodeURIComponent([p.label, p.location.split(",").pop()?.trim()].filter(Boolean).join(" "))}`}
           target="_blank" rel="noreferrer noopener"
           className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink">
          <Search size={14} />Chercher sur le web
        </a>
      </div>
      {other && (
        <form onSubmit={submit} className="mt-2 flex flex-wrap items-end gap-2">
          <Field label="Catégorie" className="min-w-[200px] flex-1">
            {(id) => (
              <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">—</option>
                {choices.categories.map((c) => <option key={c}>{c}</option>)}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" disabled={!category || busy}>Appliquer</Button>
        </form>
      )}
    </li>
  );
}

/** "nom d'une personne" -> "Nom d'une personne." */
function sentence(text: string): string {
  const t = text.trim();
  return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?…]$/.test(t) ? "" : ".");
}

/** What the search brought, said plainly: the same "no suggestion" read as
 * if the button had done nothing. */
function searchNote(s: Payee["suggestion"] | undefined): string {
  if (s?.searched === undefined) return "Le nom ne dit pas de quoi il s'agit : pas de suggestion.";
  if (s.searched === 0) return "La recherche web n'a rien rendu, et le nom seul ne suffit pas : pas de suggestion.";
  return `La recherche web a rendu ${s.searched} page${s.searched > 1 ? "s" : ""}, sans permettre de conclure : pas de suggestion.`;
}

function Pages({ s }: { s: NonNullable<Payee["suggestion"]> }) {
  if (!s.pages?.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]">
      <span className="text-muted">Sur le web :</span>
      {s.pages.map((w) => (
        <a key={w.url} href={w.url} target="_blank" rel="noreferrer noopener"
           className="max-w-[260px] truncate text-ink-2 underline underline-offset-2 hover:text-ink">{w.titre || w.url}</a>
      ))}
    </div>
  );
}
