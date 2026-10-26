/** Which model the assistant uses, chosen here; whether each key is in its
 * file (the key itself never reaches the browser); a test; and the journal
 * of what was sent. */
import { CheckCircle2, KeyRound, Sparkles } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, Input, Select } from "@/components/Form";
import { PageHeader } from "@/components/PageState";
import { Button, Callout, Chip, Note, Panel, Skeleton, cx } from "@/components/ui";
import { ApiError, send, useApi } from "@/lib/api";
import { frDate } from "@/lib/format";

interface Model { id: string; label: string; note: string }
interface Provider {
  id: string; label: string; privacy: string; where: string; default: string;
  models: Model[]; needs_key: boolean; has_key: boolean; key_file: string; running: boolean | null;
}
interface Settings {
  status: { enabled: boolean; reason?: string; label?: string; model?: string };
  provider: string | null; model: string; enabled: boolean;
  providers: Provider[];
  journal: { at: string; task: string; provider: string; model: string; chars: number; outcome?: string; tokens: number | null; usd: number | null }[];
  spending: Spend[];
  prices_as_of: string;
  merchants: { kept: number; changed: number; open: number; none: number; examples: { label: string; proposed: string; chosen: string }[] };
}
interface Spend { month: string; requests: number; sent: number; received: number; searches: number; usd: number; unpriced: number; ceiling: boolean }

const OTHER = "__other";
const TASKS: Record<string, string> = {
  merchants: "catégories des commerçants", review: "résumé du mois", why: "pourquoi ce mois",
  "ask-plan": "question (requête)", "ask-answer": "question (réponse)", scenario: "scénario en mots",
  test: "test", search: "recherche web (DeepSeek)", savings: "épargne en mots", rates: "hypothèse de marché",
};

export default function AssistantPage() {
  const { data, error, isPending } = useApi<Settings>("/api/ai/settings");
  if (error) return <Callout tone="bad" title="Les réglages n'ont pas pu être chargés">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-56" /><Skeleton className="h-72 rounded-card" /></div>;
  return (
    <>
      <PageHeader title="Assistant"
                  subtitle={data.status.enabled ? `${data.status.label} · ${data.status.model}` : "éteint"} />
      <div className="space-y-4 sm:space-y-5">
        <Choice data={data} />
        <Worth data={data} />
        <Journal data={data} />
        <Note className="px-1">
          L'assistant met en mots ce que l'app a calculé : il ne calcule aucun chiffre, et une phrase qui en cite un
          autre est écartée. Les noms de personnes partent masqués. Détail : <code>docs/assistant.md</code>.
        </Note>
      </div>
    </>
  );
}

function Choice({ data }: { data: Settings }) {
  const [provider, setProvider] = useState<string>(data.enabled && data.provider ? data.provider : "");
  const current = data.providers.find((p) => p.id === provider);
  const listed = (id: string) => !!current?.models.some((m) => m.id === id);
  const initialModel = provider === data.provider && data.model ? data.model : current?.default ?? "";
  const [model, setModel] = useState(listed(initialModel) ? initialModel : OTHER);
  const [typed, setTyped] = useState(listed(initialModel) ? "" : initialModel);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<string>();

  // A new provider starts on its own default model.
  useEffect(() => {
    if (!current) return;
    const start = provider === data.provider && data.model ? data.model : current.default;
    const known = current.models.some((m) => m.id === start);
    setModel(known ? start : OTHER);
    setTyped(known ? "" : start);
    setError(undefined);
    setTest(undefined);
  }, [provider]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await send("/api/ai/settings", { provider: provider || null, model: model === OTHER ? typed : model });
      setError(undefined);
      toast.success(provider ? `Assistant : ${current?.label}, ${model === OTHER ? typed : model}` : "Assistant éteint");
    } catch (err) {
      const errors = err instanceof ApiError ? (err.data as { errors?: Record<string, string> })?.errors : undefined;
      setError(errors ? Object.values(errors)[0] : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const runTest = async () => {
    setTest("…");
    try {
      const r = await send<{ ms: number; model: string }>("/api/ai/test", {});
      setTest(`Répond en ${(r.ms / 1000).toFixed(1)} s.`);
    } catch (err) {
      setTest((err as Error).message);
    }
  };
  const saved = data.enabled && data.provider === provider && (model === OTHER ? typed : model) === data.model;

  return (
    <Panel title="Modèle" hint="choisi ici ; la clé de chaque fournisseur reste un fichier sur le PC">
      <form onSubmit={save} className="space-y-4">
        <fieldset className="grid gap-2 sm:grid-cols-2">
          <legend className="sr-only">Fournisseur</legend>
          <Option id="" checked={provider === ""} onPick={setProvider} title="Éteint"
                  body="Aucun appel. Les boutons de l'assistant disparaissent de l'app." />
          {data.providers.map((p) => (
            <Option key={p.id} id={p.id} checked={provider === p.id} onPick={setProvider} title={p.label}
                    body={p.privacy}
                    badge={p.needs_key
                      ? (p.has_key ? <Chip tone="good"><KeyRound size={11} />clé posée</Chip> : <Chip tone="warn"><KeyRound size={11} />clé absente</Chip>)
                      : p.running === false ? <Chip tone="warn">Ollama ne tourne pas</Chip> : <Chip tone="good">sans clé</Chip>} />
          ))}
        </fieldset>

        {current && (
          <>
            {current.needs_key && !current.has_key && (
              <Callout tone="warn" icon={<KeyRound size={18} className="text-warn" />} title="La clé n'est pas encore posée">
                Créer une clé sur <b>{current.where}</b>, puis la coller seule sur une ligne dans le fichier{" "}
                <code>{current.key_file}</code> du dossier de l'app. L'app ne la demande jamais et ne l'affiche jamais.
              </Callout>
            )}
            {current.id === "ollama" && current.running === false && (
              <Callout tone="warn" title="Ollama ne répond pas sur ce PC">
                L'installer depuis <b>ollama.com</b>, puis télécharger un modèle, par exemple <code>ollama pull qwen2.5:7b</code>.
              </Callout>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Modèle" error={model !== OTHER ? error : undefined}
                     hint={current.models.find((m) => m.id === model)?.note}>
                {(id, d) => (
                  <Select id={id} aria-describedby={d} value={model} onChange={(e) => setModel(e.target.value)}>
                    {current.models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.id === current.default ? " (par défaut)" : ""}</option>)}
                    <option value={OTHER}>Autre…</option>
                  </Select>
                )}
              </Field>
              {model === OTHER && (
                <Field label="Nom exact du modèle" error={error} hint="tel que le fournisseur l'écrit">
                  {(id, d) => <Input id={id} aria-describedby={d} value={typed} invalid={!!error}
                                     onChange={(e) => setTyped(e.target.value)} placeholder={current.default} />}
                </Field>
              )}
            </div>
          </>
        )}
        {!current && error && <p role="alert" className="text-[13px] text-critical">{error}</p>}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={busy || saved || (model === OTHER && !!current && !typed.trim())}>
            {saved ? <><CheckCircle2 size={15} />Enregistré</> : "Enregistrer"}
          </Button>
          {data.status.enabled && saved && (
            <Button type="button" onClick={runTest} disabled={test === "…"}>
              <Sparkles size={14} />{test === "…" ? "Test…" : "Tester"}
            </Button>
          )}
          {test && test !== "…" && <span className="text-[13px] text-ink-2">{test}</span>}
        </div>
        {data.status.enabled && saved && <p className="text-[12.5px] text-muted">Le test envoie une requête de quelques mots, facturée comme les autres.</p>}
        {!data.status.enabled && data.provider && data.enabled && <p className="text-[13px] text-warn">{data.status.reason}</p>}
      </form>
    </Panel>
  );
}

function Option({ id, checked, onPick, title, body, badge }: {
  id: string; checked: boolean; onPick: (id: string) => void; title: string; body: string; badge?: React.ReactNode;
}) {
  return (
    <label className={cx(
      "flex cursor-pointer gap-3 rounded-2xl border p-3.5 transition",
      checked ? "border-ink bg-surface-2" : "border-hairline-2 hover:bg-surface-2/60",
    )}>
      <input type="radio" name="provider" value={id} checked={checked} onChange={() => onPick(id)} className="mt-1 accent-[var(--ink)]" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 font-medium">{title}{badge}</span>
        <span className="mt-0.5 block text-[12.5px] leading-snug text-ink-2">{body}</span>
      </span>
    </label>
  );
}

const kTokens = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : n >= 1000 ? `${Math.round(n / 1000)} k` : String(n));
/** Cents matter here: a month of DeepSeek can cost less than one. */
const usd = (v: number) => (v === 0 ? "0 $" : v < 0.001 ? "moins de 0.001 $" : `${v.toFixed(v < 1 ? 3 : 2)} $`);
const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

/** What the assistant costs, month by month, and what its merchant
 * categories were worth: kept as proposed, changed, still waiting. */
function Worth({ data }: { data: Settings }) {
  const m = data.merchants;
  const decided = m.kept + m.changed;
  return (
    <Panel title="Ce que ça coûte, ce que ça vaut" hint={`d'après les jetons que renvoie le fournisseur ; tarifs publics de ${data.prices_as_of}`}>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.spending.map((sp) => {
          const [y, mo] = sp.month.split("-").map(Number);
          const priced = sp.requests - sp.unpriced;
          return (
            <div key={sp.month} className="rounded-2xl border border-hairline p-3.5">
              <div className="eyebrow">{MONTHS[mo - 1]} {y}</div>
              <div className="num mt-1 text-[22px] font-semibold">
                {sp.requests === 0 ? "—" : priced > 0 ? `${sp.ceiling && sp.usd >= 0.001 ? "≤ " : ""}${usd(sp.usd)}` : "non chiffré"}
              </div>
              <div className="mt-0.5 text-[12.5px] text-ink-2">
                {sp.requests} requête{sp.requests > 1 ? "s" : ""} · {kTokens(sp.sent)} jetons envoyés · {kTokens(sp.received)} reçus
                {sp.searches > 0 && <> · {sp.searches} recherche{sp.searches > 1 ? "s" : ""} web</>}
              </div>
              {sp.ceiling && <div className="mt-0.5 text-[12px] text-muted">au plus : DeepSeek facture moitié moins en heures creuses</div>}
              {sp.unpriced > 0 && priced > 0 && <div className="mt-0.5 text-[12px] text-muted">{sp.unpriced} requête{sp.unpriced > 1 ? "s" : ""} d'avant le comptage, non chiffrée{sp.unpriced > 1 ? "s" : ""}</div>}
            </div>
          );
        })}
      </div>
      <div className="mt-4">
        <div className="eyebrow mb-1">Catégories proposées aux commerçants</div>
        {decided + m.open + m.none === 0 ? (
          <p className="text-[13px] text-muted">Aucune proposition encore : la page Corrections en demande pour les bénéficiaires non classés.</p>
        ) : (
          <>
            <p className="text-[13.5px]">
              {decided > 0 && <><b className="num">{Math.round((m.kept / decided) * 100)} %</b> gardées telles quelles ({m.kept} sur {decided}) · </>}
              {m.changed} corrigée{m.changed > 1 ? "s" : ""} · {m.open} en attente · {m.none} sans proposition
            </p>
            {m.examples.length > 0 && (
              <ul className="mt-1 text-[12.5px] text-ink-2">
                {m.examples.map((e) => <li key={e.label}>{e.label} : proposé {e.proposed}, classé {e.chosen}</li>)}
              </ul>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

function Journal({ data }: { data: Settings }) {
  return (
    <Panel title="Ce qui est parti" hint="les dernières requêtes ; le texte exact envoyé est dans data/ai_log.jsonl"
           foldable defaultOpen={data.journal.length > 0}>
      {data.journal.length ? (
        <ul className="divide-y divide-hairline text-[13px]">
          {data.journal.map((e, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-3 py-2">
              <span className="num w-28 shrink-0 text-muted">{frDate(e.at.slice(0, 10))} {e.at.slice(11, 16)}</span>
              <span className="min-w-0 flex-1">
                {TASKS[e.task] ?? e.task}
                {e.outcome && <span className={cx("ml-2", /échec|injoignable|illisible|aucun/.test(e.outcome) ? "text-warn" : "text-muted")}>· {e.outcome}</span>}
              </span>
              <span className="text-ink-2">{e.model}</span>
              <span className="num text-muted">
                {e.tokens != null ? `${kTokens(e.tokens)} jetons` : `${e.chars.toLocaleString("fr-CH")} car.`}
                {e.usd != null && e.usd > 0 && <> · {usd(e.usd)}</>}
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-[13px] text-muted">Rien n'a encore été envoyé.</p>}
    </Panel>
  );
}
