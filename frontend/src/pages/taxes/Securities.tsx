/** Securities held outside the statement -- an unlisted share received or
 * bought: their declared value each year, the dividend they pay into the
 * account, and the withholding tax the return gives back (`holdings.py`). */
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Field, Input } from "@/components/Form";
import { Sheet } from "@/components/Sheet";
import { Button, Note, Panel, Segmented } from "@/components/ui";
import { ApiError, send } from "@/lib/api";
import { chf } from "@/lib/format";
import type { Holding, Taxes } from "./types";

async function write(body: unknown, message: string) {
  const r = await send<{ undo: unknown }>("/api/impots/titres", body);
  toast(message, { action: { label: "Annuler", onClick: async () => { await send("/api/impots/titres", r.undo); toast("Annulé"); } } });
}

export function Securities({ data }: { data: Taxes }) {
  const [editing, setEditing] = useState<Partial<Holding> | null>(null);
  const shown = new Map(data.securities.map((s) => [s.id, s]));
  return (
    <Panel id="p-securities" title="Titres et biens hors relevé"
           hint="une action non cotée (sa valeur fiscale, son dividende, l'impôt anticipé) ou un autre bien, une montre : sa valeur"
           actions={<Button size="sm" onClick={() => setEditing({ kind: "share", quantity: 1, withholding: true, values: {} })}><Plus size={15} />Ajouter</Button>}>
      {data.holdings.length ? (
        <ul className="divide-y divide-hairline">
          {data.holdings.map((h) => {
            const s = shown.get(h.id);
            return (
              <li key={h.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-[13.5px]">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{h.name}</div>
                  <div className="truncate text-[12px] text-muted">
                    {h.kind === "other" ? `autre bien${h.quantity !== 1 ? ` × ${h.quantity}` : ""}` : `${h.quantity} titre${h.quantity > 1 ? "s" : ""}`}
                    {Object.entries(h.values).map(([y, v]) => ` · ${y} : ${chf(v, 0)}`).join("")}
                    {h.payer && ` · dividende versé par « ${h.payer} »`}
                  </div>
                </div>
                {s ? (
                  <div className="text-right">
                    <div className="num font-semibold">{chf(s.value, 0)}</div>
                    <div className="num text-[12px] text-muted">
                      {s.dividends.net ? `dividende ${chf(s.dividends.net, 2)} net · ${chf(s.dividends.gross, 2)} brut` : `au 31.12.${data.year}`}
                    </div>
                  </div>
                ) : <span className="text-[12px] text-muted">pas détenu en {data.year}</span>}
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" aria-label={`Modifier ${h.name}`} onClick={() => setEditing(h)}><Pencil size={14} /></Button>
                  <Button size="sm" variant="ghost" aria-label={`Retirer ${h.name}`} onClick={() => write({ action: "delete", id: h.id }, "Titre retiré")}><Trash2 size={14} /></Button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : <p className="text-[13px] text-muted">Aucun titre déclaré. Une action reçue en cadeau compte dans la fortune, et son dividende dans le revenu.</p>}
      {data.securities.some((s) => s.withholding && s.dividends.net) && (
        <Note>
          Un dividende suisse arrive amputé de 35 % d'impôt anticipé : le brut se déclare dans l'état des titres, et l'impôt
          anticipé (la différence entre brut et net) est remboursé par la déclaration.
        </Note>
      )}
      <HoldingSheet value={editing} years={data.years} onClose={() => setEditing(null)} />
    </Panel>
  );
}

function HoldingSheet({ value, years, onClose }: { value: Partial<Holding> | null; years: number[]; onClose: () => void }) {
  return (
    <Sheet open={!!value} onOpenChange={(o) => !o && onClose()} title={value?.id ? "Modifier" : "Ajouter un titre ou un bien"}
           description="La valeur est celle de la déclaration (cours fiscal, valeur communiquée par la société, ou valeur estimée d'un bien), pas un prix de marché.">
      {value && <HoldingForm key={value.id ?? "new"} value={value} years={years} onClose={onClose} />}
    </Sheet>
  );
}

function HoldingForm({ value, years, onClose }: { value: Partial<Holding>; years: number[]; onClose: () => void }) {
  const all = [...new Set([...years, Math.max(...years) + 1])].sort((a, b) => a - b);
  const [kind, setKind] = useState<"share" | "other">(value.kind ?? "share");
  const share = kind === "share";
  const [name, setName] = useState(value.name ?? "");
  const [quantity, setQuantity] = useState(String(value.quantity ?? 1));
  const [payer, setPayer] = useState(value.payer ?? "");
  const [withholding, setWithholding] = useState(value.withholding ?? true);
  const [since, setSince] = useState(value.since ? String(value.since) : "");
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(value.values ?? {}).map(([y, v]) => [y, String(v)])));
  const [err, setErr] = useState<string | undefined>();
  const submit = async () => {
    try {
      await write({ holding: { id: value.id, name, kind, quantity, payer, withholding, since: since || null, values } },
                  value.id ? (share ? "Titre modifié" : "Bien modifié") : (share ? "Titre ajouté" : "Bien ajouté"));
      onClose();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <div>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-2">Nature</div>
        <Segmented label="Nature" value={kind} onChange={setKind}
                   options={[{ id: "share", label: "Action non cotée" }, { id: "other", label: "Autre bien (montre, œuvre…)" }]} />
        <p className="mt-1 text-[12px] text-muted">
          {share ? "Compte en Actions dans l'allocation ; son dividende est retrouvé dans le relevé."
                 : "Compte dans la fortune et l'épargne, hors de l'allocation : pas une classe d'actifs, pas de dividende."}
        </p>
      </div>
      <Field label="Nom" error={err}>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder={share ? "Société SA, action nominative" : "Montre, tableau…"} autoFocus />}</Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={share ? "Nombre de titres" : "Nombre"}>{(id) => <Input id={id} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}</Field>
        <Field label="Détenu depuis (année)">{(id) => <Input id={id} inputMode="numeric" value={since} onChange={(e) => setSince(e.target.value)} placeholder="2024" />}</Field>
      </div>
      <div>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-2">{share ? "Valeur d'un titre au 31.12 (CHF)" : "Valeur au 31.12 (CHF)"}</div>
        <div className="grid grid-cols-3 gap-2">
          {all.map((y) => (
            <Field key={y} label={String(y)}>{(id) => (
              <Input id={id} inputMode="decimal" value={values[y] ?? ""} placeholder="—"
                     onChange={(e) => setValues({ ...values, [y]: e.target.value })} />
            )}</Field>
          ))}
        </div>
        <p className="mt-1 text-[12px] text-muted">Une année laissée vide reprend la valeur de la précédente.</p>
      </div>
      {share && <>
      <Field label="Le dividende arrive de (bénéficiaire sur le relevé)" hint="tel qu'il s'affiche dans la table des transactions">
        {(id, d) => <Input id={id} aria-describedby={d} value={payer} onChange={(e) => setPayer(e.target.value)} placeholder="Société SA" />}
      </Field>
      <label className="flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={withholding} onChange={(e) => setWithholding(e.target.checked)} className="size-4 accent-[var(--ink)]" />
        Société suisse : dividende versé net de 35 % d'impôt anticipé
      </label>
      </>}
      <div className="pt-1"><Button type="submit" variant="primary" disabled={!name.trim()}>Enregistrer</Button></div>
    </form>
  );
}
