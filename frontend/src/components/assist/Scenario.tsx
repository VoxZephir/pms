/** D: a sentence becomes changes to the plan; a cash floor, a choice of levers. */
import { Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Lines, spreadTicks } from "@/charts/Lines";
import { Field, Input } from "@/components/Form";
import { Button, Panel, cx } from "@/components/ui";
import { ApiError, post, send } from "@/lib/api";
import { MONTHS_SHORT, chf } from "@/lib/format";
import { useAi, AiBadge, Figures, aiBox, failed } from "./common";

/** "oct. 26": axis labels that fit side by side. */
function shortMonth(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
}

interface Projected {
  low: { amount: number; label: string }; end: number;
  cash: { label: string; key: string; value: number }[];
  wealth: { label: string; key: string; value: number }[] | null;
  wealth_final: number | null;
}
interface ScenarioPreview {
  supported: boolean; note?: string; name?: string;
  changes?: (Record<string, unknown> & { text: string; rows: { label: string; value: string | number; add?: boolean; remove?: boolean }[] })[];
  floor_note?: string | null;
  floor?: number | null;
  /** Every way of holding a floor with one lever, priced by the app. */
  options?: FloorOption[];
  lever?: string | null;
  base?: Projected; scenario?: Projected;
}

interface FloorOption {
  id: string; label: string; feasible: boolean; text: string; cost: string | null;
}

/** The floor, as a choice: what the plan misses, then each way of holding
 * it, priced, one of them applied. Picking another re-asks the page, from
 * the cache: no new request to the model. */
function FloorChoice({ preview, busy, pick }: { preview: ScenarioPreview; busy: boolean; pick: (id: string) => void }) {
  const options = preview.options ?? [];
  const ok = options.filter((o) => o.feasible);
  const not = options.filter((o) => !o.feasible);
  return (
    <div className={aiBox}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold">Tenir un plancher de {chf(preview.floor ?? 0, 0)} CHF</h3>
        <AiBadge>calculé par l'app</AiBadge>
      </div>
      {preview.floor_note && <p className="text-[13.5px]"><Figures text={preview.floor_note} source="calculé par l'app sur la projection" /></p>}
      {ok.length > 0 && (
        <div className="mt-2.5 space-y-1.5" role="radiogroup" aria-label="Comment tenir le plancher">
          {ok.map((o) => {
            const on = preview.lever === o.id;
            return (
              <button key={o.id} type="button" role="radio" aria-checked={on} disabled={busy}
                      onClick={() => !on && pick(o.id)}
                      className={cx("flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left text-[13.5px] transition disabled:opacity-60",
                        on ? "border-ink bg-surface-2" : "border-hairline-2 hover:bg-surface-2")}>
                <span className={cx("grid size-4 shrink-0 place-items-center rounded-full border", on ? "border-ink" : "border-hairline-2")}>
                  {on && <span className="size-2 rounded-full bg-ink" />}
                </span>
                <span className="min-w-0 flex-1">{o.text}</span>
                {o.cost && <span className="num shrink-0 text-[12.5px] text-ink-2">{o.cost}</span>}
              </button>
            );
          })}
        </div>
      )}
      {not.length > 0 && (
        <p className="mt-2 text-[12.5px] text-muted">
          Ne suffiraient pas seuls, même ramenés à zéro : {not.map((o) => o.label).join(", ")}.
        </p>
      )}
      <p className="mt-2 text-[12px] text-muted">La courbe ci-dessous montre l'option cochée ; enregistrée, elle devient un scénario à comparer.</p>
    </div>
  );
}

export function ScenarioAssist({ months }: { months: number }) {
  const ai = useAi();
  const [sentence, setSentence] = useState("");
  const [preview, setPreview] = useState<ScenarioPreview | null>(null);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"auto" | "cash" | "wealth">("auto");
  if (!ai?.enabled) return null;

  const translate = async (e?: FormEvent, lever?: string) => {
    e?.preventDefault();
    if (!sentence.trim()) return;
    setBusy(true);
    try {
      // The same sentence again is answered from the cache: choosing another
      // lever costs no new request to the model.
      const r = await post<ScenarioPreview>(`/api/ai/scenario?months=${months}`, { sentence, lever });
      setPreview(r);
      setName(r.name ?? "");
      setNameError(undefined);
    } catch (err) {
      const data = err instanceof ApiError ? err.data as ScenarioPreview | undefined : undefined;
      if (data && data.supported === false) setPreview(data);
      else failed("La phrase n'a pas pu être traduite", err);
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!preview?.changes) return;
    try {
      await send(`/api/ai/scenario?months=${months}`, { action: "save", name, changes: preview.changes });
      toast.success(`Scénario « ${name} » enregistré`, {
        description: "Il apparaît dans la comparaison ; le plan affiché n'a pas changé.",
        action: { label: "Annuler", onClick: async () => { await send(`/api/previsions?months=${months}`, { action: "plan-delete", name }); toast("Scénario retiré"); } },
      });
      setPreview(null);
      setSentence("");
    } catch (err) {
      const errors = err instanceof ApiError ? (err.data as { errors?: Record<string, string> } | undefined)?.errors : undefined;
      if (errors) setNameError(errors.name ?? errors.changes);
      else failed("Le scénario n'a pas pu être enregistré", err);
    }
  };

  const b = preview?.base, s = preview?.scenario;
  // The wealth curve when the pockets are known, the cash otherwise: the
  // mockup's "Patrimoine projeté", honest about which one it draws.
  // The cash by default for a floor (it is what the floor is about), the
  // wealth otherwise when the pockets are known; the reader can switch.
  const canWealth = !!(b?.wealth && s?.wealth);
  const wealth = canWealth && (view === "wealth" || (view === "auto" && !preview?.floor));
  const line = (p: Projected) => (wealth ? p.wealth! : p.cash);
  const final = (p: Projected) => (wealth ? p.wealth_final ?? p.end : p.end);
  const gap = b && s ? final(s) - final(b) : 0;
  return (
    <Panel title="Scénario en mots" hint="une phrase devient des lignes du plan, montrées avant d'être enregistrées ; le rendement reste celui que tu as déclaré">
      <form onSubmit={translate} className="flex flex-wrap items-end gap-2">
        <Field label="Nouveau scénario" className="min-w-[240px] flex-1">
          {(id) => <Input id={id} data-scenario-sentence="" value={sentence} onChange={(e) => setSentence(e.target.value)}
                          placeholder="Et si je verse 500 de plus par mois sur IBKR dès janvier ?" maxLength={400} />}
        </Field>
        <Button type="submit" disabled={busy || !sentence.trim()}><Sparkles size={14} />{busy ? "Traduction…" : "Traduire"}</Button>
      </form>
      {preview && !preview.supported && <p className="mt-3 text-[13.5px] text-ink-2">{preview.note}</p>}
      {preview && !preview.supported && !!preview.options?.length && (
        <p className="mt-1.5 text-[12.5px] text-muted">Leviers essayés : {preview.options.map((o) => o.label).join(", ")}.</p>
      )}
      {preview?.supported && b && s && (
        <div className="mt-4 space-y-4">
          {preview.options?.length ? <FloorChoice preview={preview} busy={busy} pick={(id) => void translate(undefined, id)} /> : (
          <div className={aiBox}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-[15px] font-semibold">Ce que j'ai compris</h3>
              <AiBadge>à valider</AiBadge>
            </div>
            {preview.floor_note && <p className="mb-2 text-[13.5px]"><Figures text={preview.floor_note} source="calculé par l'app sur la projection" /></p>}
            <div className="space-y-1 text-[13px]">
              {preview.changes!.flatMap((c, i) => c.rows.map((r, k) => (
                <div key={`${i}-${k}`} className={cx("flex justify-between gap-3 rounded-lg px-2.5 py-1.5",
                  r.add ? "bg-[color-mix(in_srgb,var(--good)_10%,transparent)]"
                    : r.remove ? "bg-[color-mix(in_srgb,var(--critical)_10%,transparent)]" : "bg-surface-2")}>
                  <span className="min-w-0">{r.label}</span>
                  <span className="num shrink-0 text-right">{typeof r.value === "number" ? chf(r.value) : r.value}</span>
                </div>
              )))}
            </div>
            <p className="mt-2 text-[12px] text-muted">Les montants et les dates viennent de ta phrase ; la projection est celle des Prévisions, l'assistant ne la calcule pas.</p>
          </div>
          )}
          <div className="rounded-2xl border border-hairline bg-surface p-3.5">
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[15px] font-semibold">{wealth ? "Patrimoine projeté" : "Cash projeté"}</h3>
              <span className={cx("num text-[13px] font-semibold", gap >= 0 ? "text-good" : "text-critical")}>
                {gap >= 0 ? "+" : "−"}{chf(Math.abs(gap), 0)} à l'horizon ({line(s)[line(s).length - 1]?.label})
              </span>
            </div>
            {canWealth && (
              <div className="mb-2 flex gap-1 text-[12.5px]" role="group" aria-label="Courbe affichée">
                {(["cash", "wealth"] as const).map((v) => (
                  <button key={v} type="button" aria-pressed={wealth === (v === "wealth")}
                          onClick={() => setView(v)}
                          className={cx("rounded-lg px-2.5 py-1", wealth === (v === "wealth") ? "bg-surface-2 font-semibold text-ink" : "text-muted hover:text-ink")}>
                    {v === "cash" ? "Cash" : "Patrimoine"}
                  </button>
                ))}
              </div>
            )}
            <Lines xs={line(s).map((_, i) => i)} height={190} zero={false}
                   series={[
                     { key: "base", name: "Plan actuel", color: "var(--unsorted)", values: line(b).map((r) => r.value), dash: true },
                     { key: "scenario", name: "Avec le scénario", color: "var(--s0)", values: line(s).map((r) => r.value), area: true },
                   ]}
                   refs={!wealth && preview.floor ? [{ value: preview.floor, color: "var(--critical)", label: `plancher ${chf(preview.floor, 0)}`, dash: true }] : []}
                   tipFormat={(v) => `${chf(v, 0)} CHF`}
                   xLabel={(i) => line(s)[i]?.label ?? ""}
                   xTicks={(w) => spreadTicks(line(s).length, w, (i) => shortMonth(line(s)[i].key), 56)}
                   ariaLabel={`${wealth ? "Patrimoine" : "Solde"} projeté, plan actuel et scénario`} />
            <div className="mt-1 flex flex-wrap gap-4 text-[12px] text-ink-2">
              <span className="flex items-center gap-1.5"><i className="inline-block h-0.5 w-3.5 border-t-2 border-dashed border-unsorted" />Plan actuel</span>
              <span className="flex items-center gap-1.5"><i className="inline-block h-0.5 w-3.5 bg-s0" />Avec le scénario</span>
              <span className="text-muted">point bas {chf(s.low.amount, 0)} contre {chf(b.low.amount, 0)}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Nom du scénario" error={nameError} className="min-w-[200px] flex-1">
              {(id, d) => <Input id={id} aria-describedby={d} value={name} invalid={!!nameError} maxLength={60}
                                 onChange={(e) => setName(e.target.value)} />}
            </Field>
            <Button variant="primary" onClick={save} disabled={!name.trim()}>Enregistrer le scénario</Button>
            <Button onClick={() => { setPreview(null); document.querySelector<HTMLInputElement>("[data-scenario-sentence]")?.focus(); }}>Modifier</Button>
          </div>
        </div>
      )}
    </Panel>
  );
}
