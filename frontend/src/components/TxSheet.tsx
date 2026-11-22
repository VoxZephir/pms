/** One movement: what the bank printed, and where to put it.
 *
 * The reclassification is the same `/api/reclassify` the old drag-and-drop
 * used: "cette ligne" pins this movement, "tout ce bénéficiaire" writes a
 * rule that also catches next month's. Every correction can be undone from
 * the toast -- the server returns what to restore. */
import { Check, Luggage, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { send, useApi } from "@/lib/api";
import { bucketLabel, chf, frLongDay } from "@/lib/format";
import type { Choices, Tx } from "@/lib/types";

import { Sheet } from "./Sheet";
import { Amount, Initial } from "./TxList";
import { Button, Chip, Segmented, cx } from "./ui";

interface Undo { scope: string; key: string; match: string; mode: string; restore: unknown }

export function TxSheet({ tx, onClose }: { tx: Tx | null; onClose: () => void }) {
  return (
    <Sheet open={!!tx} onOpenChange={(o) => !o && onClose()} title={tx?.label ?? ""}
           description={tx ? frLongDay(tx.date) : undefined}>
      {tx && <TxDetail key={tx.key} tx={tx} onDone={onClose} />}
    </Sheet>
  );
}

function TxDetail({ tx, onDone }: { tx: Tx; onDone: () => void }) {
  const { data: choices } = useApi<Choices>("/api/choices");
  const [scope, setScope] = useState<"pin" | "merchant">("pin");
  const [category, setCategory] = useState(tx.category);
  const [sub, setSub] = useState(tx.subcategory);
  const [bucket, setBucket] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const cats = useMemo(() => {
    const all = choices?.categories ?? [];
    const f = filter.trim().toLowerCase();
    return f ? all.filter((c) => c.toLowerCase().includes(f)) : all;
  }, [choices, filter]);
  const subs = choices?.subcategories[category] ?? [];
  const changed = category !== tx.category || sub !== tx.subcategory || bucket !== "";

  const apply = async () => {
    setBusy(true);
    try {
      const r = await send<{ count: number; scope: string; match: string; undo: Undo }>("/api/reclassify", {
        key: tx.key, scope, category: category !== tx.category || sub !== tx.subcategory ? category : "",
        subcategory: sub, bucket,
      });
      onDone();
      toast.success(
        r.scope === "merchant"
          ? `${r.count} mouvement${r.count > 1 ? "s" : ""} de ${r.match} reclassé${r.count > 1 ? "s" : ""}`
          : `Reclassé en ${category || bucket}`,
        {
          description: r.scope === "merchant" ? "Règle enregistrée : les prochains suivront." : undefined,
          action: {
            label: "Annuler",
            onClick: async () => {
              await send("/api/reclassify/undo", r.undo);
              toast("Correction annulée");
            },
          },
        },
      );
    } catch (e) {
      toast.error("La correction a échoué", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Initial label={tx.label} tone={tx.amount > 0 ? "var(--good)" : undefined} />
        <div className="min-w-0 flex-1">
          <Amount tx={tx} className="text-[22px] tracking-tight" />
          {tx.currency !== "CHF" && <div className="num text-[13px] text-muted">{chf(tx.chf)} CHF</div>}
        </div>
        {tx.overridden && <Chip tone="accent">corrigé</Chip>}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-2xl bg-surface-2/60 px-4 py-3 text-[13px]">
        <dt className="text-muted">Type</dt><dd className="min-w-0 break-words">{tx.kind}</dd>
        {tx.merchant && <><dt className="text-muted">Bénéficiaire</dt><dd className="min-w-0 break-words">{tx.merchant}</dd></>}
        {tx.location && <><dt className="text-muted">Lieu</dt><dd className="min-w-0 break-words">{tx.location}</dd></>}
        <dt className="text-muted">Classement</dt>
        <dd>{tx.category || "—"}{tx.subcategory ? ` · ${tx.subcategory}` : ""}{tx.bucket ? ` · ${bucketLabel(tx.bucket)}` : ""}</dd>
        {tx.account && <><dt className="text-muted">Compte</dt><dd className="capitalize">{tx.account}</dd></>}
        <dt className="text-muted">Référence</dt><dd className="num break-all">{tx.key.split(":")[0]}</dd>
        {tx.detail.length > 2 && (
          <><dt className="text-muted">Détail</dt><dd className="min-w-0 break-words text-ink-2">{tx.detail.slice(1).join(" · ")}</dd></>
        )}
      </dl>

      <TxAdvance tx={tx} onDone={onDone} />

      {!tx.advance_of && <>
      <TxProjects tx={tx} />

      <div>
        <div className="eyebrow mb-2">Reclasser</div>
        <Segmented
          label="Portée de la correction"
          value={scope}
          onChange={setScope}
          options={[
            { id: "pin", label: "Cette ligne" },
            { id: "merchant", label: "Tout ce bénéficiaire" },
          ]}
        />
        <p className="mt-2 text-[12.5px] text-muted">
          {scope === "pin"
            ? "Ne change que ce mouvement."
            : `Écrit une règle sur « ${tx.label} » : ses mouvements passés et futurs suivent.`}
        </p>
      </div>

      <div>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrer les catégories"
                 autoCapitalize="off" autoCorrect="off" spellCheck={false}
                 className="h-10 w-full rounded-xl border border-hairline-2 bg-surface pl-9 pr-3 text-[16px] sm:text-[14px]" />
        </div>
        <div className="mt-2 flex max-h-56 flex-wrap gap-1.5 overflow-y-auto">
          {cats.map((c) => (
            <button key={c} type="button" onClick={() => { setCategory(c); setSub(""); }}
                    className={cx(
                      "inline-flex items-center gap-1 rounded-xl border px-3 py-2 text-[13px] font-medium transition",
                      c === category ? "border-transparent bg-ink text-page" : "border-hairline-2 hover:bg-surface-2",
                    )}>
              {c === category && <Check size={13} />}{c}
            </button>
          ))}
        </div>
      </div>

      {subs.length > 0 && (
        <div>
          <div className="eyebrow mb-2">Sous-catégorie</div>
          <div className="flex flex-wrap gap-1.5">
            {["", ...subs].map((s) => (
              <button key={s || "none"} type="button" onClick={() => setSub(s)}
                      className={cx("rounded-xl border px-3 py-1.5 text-[12.5px] transition",
                        s === sub ? "border-transparent bg-ink text-page" : "border-hairline-2 hover:bg-surface-2")}>
                {s || "Aucune"}
              </button>
            ))}
          </div>
        </div>
      )}

      {choices && (
        <div>
          <div className="eyebrow mb-2">Besoin, envie, épargne <span className="normal-case tracking-normal">(facultatif)</span></div>
          <Segmented
            label="Bloc"
            value={bucket}
            onChange={setBucket}
            options={[{ id: "", label: "Selon la catégorie" }, ...choices.buckets.map((b) => ({ id: b, label: bucketLabel(b) }))]}
          />
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <Button variant="primary" size="lg" className="flex-1" disabled={!changed || busy} onClick={apply}>
          {scope === "merchant" ? "Appliquer à tout le bénéficiaire" : "Appliquer"}
        </Button>
      </div>
      </>}
    </div>
  );
}

type AdvanceMode = "none" | "half" | "all" | "due" | "other";
interface Advances { owed: number; advanced: number; repaid: number; count: number; open_since: string | null }

/** Paid for someone who pays it back (a Twint for a partner without Twint),
 * or that repayment: the part named here leaves spending and income alike,
 * and the rest of the row keeps its category (`overrides.split_advances`). */
function TxAdvance({ tx, onDone }: { tx: Tx; onDone: () => void }) {
  const { data: due } = useApi<Advances>("/api/advances");
  const out = tx.printed < 0;
  const gross = Math.abs(tx.printed);
  const cents = (n: number) => Math.round(n * 100) / 100;
  const half = cents(gross / 2);
  // What is still owed, not counting this row's own repayment.
  const owed = due ? cents(due.owed + (!out && tx.currency === "CHF" ? tx.advanced : 0)) : 0;
  const offerDue = !out && tx.currency === "CHF" && owed > 0.005 && owed < gross - 0.005;
  const initial: AdvanceMode = !tx.advanced ? "none"
    : Math.abs(tx.advanced - gross) < 0.005 ? "all"
    : out && Math.abs(tx.advanced - half) < 0.005 ? "half"
    : offerDue && Math.abs(tx.advanced - owed) < 0.005 ? "due" : "other";
  const [mode, setMode] = useState<AdvanceMode>(initial);
  const [other, setOther] = useState(tx.advanced && initial === "other" ? String(tx.advanced) : "");
  const [busy, setBusy] = useState(false);

  if (tx.category === "Virement interne" || tx.kind.startsWith("Transfert automatisé") || tx.kind.startsWith("Transfert Forex") || !gross) return null;

  const typed = Number(other.replace(/'/g, "").replace(",", "."));
  const amount = mode === "none" ? 0 : mode === "all" ? gross : mode === "half" ? half
    : mode === "due" ? owed : Number.isFinite(typed) ? cents(Math.abs(typed)) : NaN;
  const valid = Number.isFinite(amount) && amount <= gross + 0.005 && (mode !== "other" || amount > 0);
  const changed = valid && Math.abs(amount - tx.advanced) >= 0.005;

  const save = async () => {
    setBusy(true);
    try {
      const r = await send<{ undo: Undo }>("/api/advance", { key: tx.advance_of || tx.key, amount });
      onDone();
      toast.success(amount === 0 ? "Plus une avance"
        : out ? `${chf(amount)} ${tx.currency} avancés : hors des dépenses`
        : `${chf(amount)} ${tx.currency} remboursés : hors des revenus`, {
        description: amount > 0 && amount < gross - 0.005 ? `Le reste (${chf(gross - amount)}) garde sa catégorie.` : undefined,
        action: { label: "Annuler", onClick: async () => { await send("/api/reclassify/undo", r.undo); toast("Annulé"); } },
      });
    } catch (e) {
      toast.error("L'avance n'a pas été enregistrée", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const options: { id: AdvanceMode; label: string }[] = out
    ? [{ id: "none", label: "Non" }, { id: "half", label: "La moitié" }, { id: "all", label: "Tout" }, { id: "other", label: "Montant" }]
    : [{ id: "none", label: "Non" }, ...(offerDue ? [{ id: "due" as const, label: `Le dû · ${chf(owed)}` }] : []),
       { id: "all", label: "Tout" }, { id: "other", label: "Montant" }];

  return (
    <div data-advance>
      <div className="eyebrow mb-2">{out ? "Payé pour quelqu'un qui te rembourse ?" : "Rembourse une avance ?"}</div>
      <Segmented label={out ? "Part avancée" : "Part remboursée"} value={mode} onChange={setMode} options={options} />
      {mode === "other" && (
        <div className="mt-2 flex items-center gap-2">
          <input value={other} onChange={(e) => setOther(e.target.value)} inputMode="decimal" placeholder="0.00" aria-label="Montant avancé"
                 className="num h-10 w-32 rounded-xl border border-hairline-2 bg-surface px-3 text-[16px] sm:text-[14px]" />
          <span className="text-[13px] text-muted">{tx.currency} sur {chf(gross)}</span>
        </div>
      )}
      <p className="mt-2 text-[12.5px] text-muted">
        {mode === "none"
          ? (out ? "Si tu as payé pour quelqu'un, la part avancée sort des dépenses ; elle reste due jusqu'à son remboursement."
                 : "Si cet argent te rembourse un paiement fait pour quelqu'un, il sort des revenus.")
          : !valid ? `Au plus ${chf(gross)} ${tx.currency}.`
          : amount < gross - 0.005
            ? `${chf(amount)} ${out ? "avancés" : "remboursés"}, hors ${out ? "dépenses" : "revenus"} ; ${chf(gross - amount)} restent ${tx.advance_of || tx.category === "Avances" ? "dans la catégorie de la ligne" : `en ${tx.category}`}.`
            : `Toute la ligne sort des ${out ? "dépenses" : "revenus"}.`}
        {due && due.count > 0 && <> {due.owed > 0.005 ? `On te doit en tout ${chf(due.owed)} CHF.` : "Toutes les avances sont remboursées."}</>}
      </p>
      {changed && (
        <Button className="mt-2" onClick={save} disabled={busy}>{amount === 0 ? "Retirer l'avance" : "Enregistrer l'avance"}</Button>
      )}
    </div>
  );
}

/** The projects this movement can join or leave (`/projets`): one tap each,
 * undone from the toast. */
function TxProjects({ tx }: { tx: Tx }) {
  const { data } = useApi<{ projects: { id: string; name: string; member: boolean }[] }>("/api/projets/liste", `key=${encodeURIComponent(tx.key)}`);
  if (!data || !data.projects.length) return null;
  const toggle = async (p: { id: string; name: string; member: boolean }) => {
    const r = await send<{ undo: unknown }>("/api/projets", { action: p.member ? "remove" : "add", id: p.id, keys: [tx.key] });
    toast(p.member ? `Retiré de « ${p.name} »` : `Ajouté à « ${p.name} »`, {
      action: { label: "Annuler", onClick: async () => { await send("/api/projets", r.undo); toast("Annulé"); } },
    });
  };
  return (
    <div>
      <div className="eyebrow mb-2">Projet</div>
      <div className="flex flex-wrap gap-1.5">
        {data.projects.map((p) => (
          <button key={p.id} type="button" onClick={() => toggle(p)} aria-pressed={p.member}
                  className={cx("inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[12.5px] font-medium transition",
                    p.member ? "border-transparent bg-ink text-page" : "border-hairline-2 hover:bg-surface-2")}>
            {p.member ? <Check size={13} /> : <Luggage size={13} />}{p.name}
          </button>
        ))}
      </div>
    </div>
  );
}
