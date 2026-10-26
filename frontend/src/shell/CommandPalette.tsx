/** Ctrl K: go anywhere, to any period, find any transaction -- by typing.
 * With a model configured, a question in French too: the model turns it into
 * a query, Flask runs it, and the answer ends on the view that shows it. */
import { Command } from "cmdk";
import { ArrowLeft, ArrowRight, CalendarRange, Moon, Search, Sparkles, Tag } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { AiBadge, AnswerTable, Figures, Sources, answerHref, useAi, type AskAnswer } from "@/components/Assist";
import { Input } from "@/components/Form";
import { Button } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { chf, frDate } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import type { Choices, Period, TxPage } from "@/lib/types";
import { nextParams, useView, withQuery } from "@/lib/url";

import { NAV, UPLOAD } from "./nav";

const fold = (s: string) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();

/** Every typed word somewhere in the item, accents and case aside -- the
 * rule of the transactions search. cmdk's fuzzy default let "coop" match
 * "catégorie Shopping" (c, o, o, p, in order). */
function wordFilter(value: string, search: string, keywords?: string[]): number {
  const hay = fold([value, ...(keywords ?? [])].join(" "));
  const words = fold(search).split(/\s+/).filter(Boolean);
  if (!words.length) return 1;
  return words.every((w) => hay.includes(w)) ? 1 - Math.min(0.5, hay.length / 400) : 0;
}

/** The last questions asked, kept in this browser only (a convenience:
 * asked again, a question answers from the server's cache, at no cost). */
const RECENT_KEY = "pms-recent-questions";
function recent(): string[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as string[]; } catch { return []; }
}
function remember(q: string) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([q, ...recent().filter((x) => x !== q)].slice(0, 5))); } catch { /* private mode */ }
}

/** What the assistant is good at, as first questions to try. */
const STARTERS = [
  "Combien j'ai dépensé en restaurants cette année, et face à l'an passé ?",
  "Où est passé mon argent le mois dernier ?",
  "Est-ce que je descends sous 10'000 CHF de cash dans l'année ?",
  "Quels sont mes abonnements et combien par an ?",
];

export function CommandPalette({
  open, onOpenChange, theme,
}: { open: boolean; onOpenChange: (v: boolean) => void; theme: ReturnType<typeof useTheme> }) {
  const navigate = useNavigate();
  const { params, pageHref } = useView();
  const [search, setSearch] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const ai = useAi();
  const { data: period } = useApi<Period>("/api/period", params.toString(), open);
  const { data: choices } = useApi<Choices>("/api/choices", undefined, open);
  const needle = search.trim();
  const { data: hits } = useApi<TxPage>(
    "/api/transactions",
    new URLSearchParams({ preset: "all", q: needle, per: "20" }),
    open && needle.length >= 2,
  );

  const run = (fn: () => void) => {
    onOpenChange(false);
    setSearch("");
    setAsked(null);
    fn();
  };
  const goPeriod = (patch: Record<string, string | null>) => {
    const path = window.location.pathname || "/";
    const onPeriodPage = NAV.some((n) => n.period && (n.to === "/" ? path === "/" : path.startsWith(n.to)));
    navigate(withQuery(onPeriodPage ? path : "/", nextParams(params, patch)));
  };

  const item = "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] data-[selected=true]:bg-surface-2";
  // The heading only: on the group itself, uppercase and grey reached every item.
  const group = "px-2 pb-1 pt-3 [&_[cmdk-group-heading]]:px-1 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-muted";

  // Closed is forgotten: reopened, the palette starts empty, on the
  // starter questions and the pages -- not on last time's search.
  return (
    <Dialog.Root open={open} onOpenChange={(v) => { if (!v) { setAsked(null); setSearch(""); } onOpenChange(v); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-[10vh] z-50 w-[calc(100vw-24px)] max-w-xl -translate-x-1/2 overflow-hidden rounded-[22px] border border-hairline bg-surface shadow-pop outline-none data-[state=open]:animate-[pop-in_.16s_ease-out]"
        >
          <Dialog.Title className="sr-only">Recherche et commandes</Dialog.Title>
          <Dialog.Description className="sr-only">Pages, périodes, catégories et transactions</Dialog.Description>
          {asked ? (
            <Ask question={asked} onBack={() => setAsked(null)} onOpen={(href) => run(() => navigate(href))} />
          ) : (
          <Command loop label="Recherche et commandes" filter={wordFilter}>
            <div className="flex items-center gap-3 border-b border-hairline px-4">
              <Search size={18} className="text-muted" />
              <Command.Input
                value={search}
                onValueChange={setSearch}
                autoFocus
                placeholder="Page, période, catégorie, bénéficiaire, montant…"
                autoCapitalize="off" autoCorrect="off" spellCheck={false}
                className="h-14 flex-1 bg-transparent text-[16px] outline-none placeholder:text-muted"
              />
              <kbd className="hidden rounded-md border border-hairline-2 px-1.5 text-[11px] text-muted sm:block">Échap</kbd>
            </div>
            <Command.List className="max-h-[60vh] overflow-y-auto px-2 pb-2">
              <Command.Empty className="px-4 py-8 text-center text-[14px] text-muted">Rien ne correspond.</Command.Empty>

              {ai?.enabled && needle.length === 0 && (
                <Command.Group heading="Demander à l'assistant" className={group}>
                  {[...recent(), ...STARTERS.filter((q) => !recent().includes(q))].slice(0, 6).map((q) => (
                    <Command.Item key={q} value={`question ${q}`} className={item} onSelect={() => setAsked(q)}>
                      <Sparkles size={16} className="text-s6" />
                      <span className="min-w-0 flex-1 truncate">{q}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              <Command.Group heading="Pages" className={group}>
                {[...NAV, UPLOAD].map((n) => (
                  <Command.Item key={n.to} value={`page ${n.label}`} className={item}
                                onSelect={() => run(() => navigate(pageHref(n.to)))}>
                    <n.icon size={16} className="text-muted" />
                    <span className="flex-1">{n.label}</span>
                    <ArrowRight size={14} className="text-muted" />
                  </Command.Item>
                ))}
                <Command.Item value="page tri twint" className={item} onSelect={() => run(() => navigate("/corrections/tri"))}>
                  <Tag size={16} className="text-muted" /><span className="flex-1">Trier les Twint</span>
                </Command.Item>
              </Command.Group>

              {period && (
                <Command.Group heading="Périodes" className={group}>
                  {period.presets.map((p) => (
                    <Command.Item key={p.id} value={`periode ${p.group} ${p.label}`} className={item}
                                  onSelect={() => run(() => goPeriod({ preset: p.id, from: null, to: null, grain: "auto" }))}>
                      <CalendarRange size={16} className="text-muted" />
                      <span className="flex-1">{p.group === "Complet" ? p.label : `${p.group} · ${p.label}`}</span>
                      <span className="num text-[12px] text-muted">{frDate(p.start)} → {frDate(p.end)}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              {choices && (
                <Command.Group heading="Catégories" className={group}>
                  {choices.categories.map((c) => (
                    <Command.Item key={c} value={`categorie ${c}`} className={item}
                                  onSelect={() => run(() => navigate(withQuery("/transactions", nextParams(params, { category: c }))))}>
                      <Tag size={16} className="text-muted" />
                      <span className="flex-1">{c}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              <Command.Group heading="Actions" className={group}>
                <Command.Item value="theme sombre clair" className={item} onSelect={() => run(theme.toggle)}>
                  <Moon size={16} className="text-muted" /><span>Basculer le thème</span>
                </Command.Item>
              </Command.Group>

              {ai?.enabled && needle.length >= 4 && (
                <Command.Group heading="Assistant" className={group} forceMount>
                  <Command.Item value="__ask" forceMount className={item} onSelect={() => setAsked(needle)}>
                    <Sparkles size={16} className="text-s6" />
                    <span className="min-w-0 flex-1 truncate">Demander : « {needle} »</span>
                  </Command.Item>
                </Command.Group>
              )}

              {/* Last, and always there once two letters are typed: a page or a
                  period that matches comes first, the search over the whole
                  ledger is never out of reach. The server did the matching. */}
              {needle.length >= 2 && (
                <Command.Group heading="Transactions" className={group} forceMount>
                  <Command.Item value="__search" forceMount className={item}
                                onSelect={() => run(() => navigate(withQuery("/transactions", new URLSearchParams({ preset: "all", q: needle }))))}>
                    <Search size={16} className="text-muted" />
                    <span className="flex-1">Chercher « {needle} » dans toutes les transactions</span>
                    {hits && <span className="num text-[12.5px] text-muted">{hits.total}</span>}
                  </Command.Item>
                  {hits?.rows.slice(0, 6).map((t) => (
                    <Command.Item key={t.key} value={`__tx ${t.key}`} forceMount className={item}
                                  onSelect={() => run(() => navigate(withQuery("/transactions", new URLSearchParams({ from: t.date, to: t.date, q: needle }))))}>
                      <span className="num w-20 shrink-0 text-[12.5px] text-muted">{frDate(t.date)}</span>
                      <span className="min-w-0 flex-1 truncate">{t.label}</span>
                      <span className={`num text-[13px] ${t.amount < 0 ? "" : "text-good"}`}>{chf(t.amount)} {t.currency}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
            </Command.List>
          </Command>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A conversation of a few questions: the model plans each query, Flask
 * runs it, the model says the result in a few sentences whose numbers the
 * server checked, and the app's own table follows. A follow-up carries the
 * last exchanges, so "et l'année d'avant ?" means something. */
function Ask({ question, onBack, onOpen }: { question: string; onBack: () => void; onOpen: (href: string) => void }) {
  const [turns, setTurns] = useState<{ question: string; answer?: AskAnswer; error?: string }[]>([{ question }]);
  const [draft, setDraft] = useState("");
  const pending = turns.some((t) => !t.answer && !t.error);

  useEffect(() => {
    const i = turns.length - 1;
    const turn = turns[i];
    if (turn.answer || turn.error) return;
    let live = true;
    const history = turns.slice(0, i).filter((t) => t.answer)
      .map((t) => ({ question: t.question, answer: t.answer!.answer }));
    post<AskAnswer>("/api/ai/ask", { question: turn.question, history })
      .then((answer) => { if (live) setTurns((all) => all.map((t, k) => (k === i ? { ...t, answer } : t))); })
      .catch((e: Error) => { if (live) setTurns((all) => all.map((t, k) => (k === i ? { ...t, error: e.message } : t))); });
    return () => { live = false; };
  }, [turns]);

  useEffect(() => { remember(question); }, [question]);
  const askNext = (q: string) => {
    if (!q.trim() || pending) return;
    setTurns((all) => [...all, { question: q.trim() }]);
    remember(q.trim());
    setDraft("");
  };
  const last = turns[turns.length - 1];

  return (
    <div className="max-h-[75vh] overflow-y-auto p-4 sm:p-5" aria-live="polite">
      <button type="button" onClick={onBack} className="-ml-1 mb-2 flex items-center gap-1.5 rounded-lg p-1 text-[13px] text-muted hover:bg-surface-2">
        <ArrowLeft size={15} />Recherche
      </button>
      <div className="space-y-5">
        {turns.map((t, i) => (
          <div key={i}>
            <p className="text-[15px] font-medium">{t.question}</p>
            <div className="mt-2 rounded-2xl border border-[color-mix(in_srgb,var(--s6)_25%,transparent)] bg-[color-mix(in_srgb,var(--s6)_6%,var(--surface))] p-3.5">
              <div className="mb-1.5 flex items-start justify-between gap-2">
                <h3 className="min-w-0 text-[15px] font-semibold">
                  {t.answer?.title ?? "Réponse"}{t.answer?.scope && <span className="font-normal text-muted"> · {t.answer.scope}</span>}
                </h3>
                <AiBadge>réponse</AiBadge>
              </div>
              {t.error ? <p className="text-[14px] text-critical">{t.error}</p>
                : t.answer ? <p className="text-[15px] leading-relaxed"><Figures text={t.answer.answer} /></p>
                  : <p className="text-[14px] text-muted">L'app cherche les chiffres…</p>}
              {t.answer?.table && <AnswerTable table={t.answer.table} focus={t.answer.focus} />}
              {t.answer?.supported && <Sources items={t.answer.sources ?? []} />}
            </div>
            {t.answer?.supported && t.answer.view && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button size="sm" variant="primary" onClick={() => onOpen(answerHref(t.answer!.view!))}>Ouvrir cette vue<ArrowRight size={14} /></Button>
                <span className="min-w-0 truncate text-[11.5px] text-muted">{answerHref(t.answer.view)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
      {last.answer && last.answer.follow_ups.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {last.answer.follow_ups.map((f) => (
            <button key={f} type="button" onClick={() => askNext(f)}
                    className="rounded-full border border-hairline-2 bg-surface-2 px-3 py-1.5 text-left text-[13px] text-ink-2 hover:bg-surface-3">
              {f}
            </button>
          ))}
        </div>
      )}
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); askNext(draft); }}>
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Une autre question…"
               aria-label="Une autre question" maxLength={300} />
        <Button type="submit" variant="primary" disabled={pending || !draft.trim()}>Demander</Button>
      </form>
    </div>
  );
}
