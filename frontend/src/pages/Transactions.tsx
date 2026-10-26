/** Every movement of the window: search, filters, sorting, bulk corrections.
 *
 * The filters live in the URL like everything else, and the server sorts
 * and pages (a client-side sort would only reorder the rows already loaded).
 * More rows load as the list scrolls. A selection -- or the whole filter --
 * can be reclassified at once, and undone from the toast. */
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Download, ListChecks, Search, SlidersHorizontal, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/PageState";
import { Sheet } from "@/components/Sheet";
import { Amount, TxGroups, TxRow } from "@/components/TxList";
import { TxSheet } from "@/components/TxSheet";
import { Button, Card, Chip, Dot, IconButton, Segmented, Skeleton, cx } from "@/components/ui";
import { getJSON, send, useApi } from "@/lib/api";
import { bucketLabel, chf, frDate, plural } from "@/lib/format";
import { useDesktop } from "@/lib/hooks";
import type { Choices, Tx, TxPage } from "@/lib/types";
import { TABLE_KEYS, VIEW_KEYS, WINDOW_KEYS, nextParams, useView, withQuery } from "@/lib/url";
import { Summary } from "./transactions/Summary";

const KEEP = [...WINDOW_KEYS, ...VIEW_KEYS, ...TABLE_KEYS];
const SORTS = [
  { id: "date", label: "Date" },
  { id: "chf", label: "Montant" },
  { id: "label", label: "Bénéficiaire" },
  { id: "category", label: "Catégorie" },
];

export default function TransactionsPage() {
  const view = useView();
  const desktop = useDesktop();
  const params = view.params;
  const listQuery = useMemo(() => {
    const p = nextParams(params, {}, KEEP);
    p.delete("page");
    return p.toString();
  }, [params]);

  const query = useInfiniteQuery({
    queryKey: ["/api/transactions:list", listQuery],
    queryFn: ({ pageParam }) => getJSON<TxPage>("/api/transactions", `${listQuery}${listQuery ? "&" : ""}page=${pageParam}`),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  });
  const first = query.data?.pages[0];
  const rows = useMemo(() => query.data?.pages.flatMap((p) => p.rows) ?? [], [query.data]);

  const set = (patch: Record<string, string | null>) =>
    view.navigate(withQuery(view.pathname, nextParams(params, patch, KEEP)), { replace: true, preventScrollReset: true });

  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const bucket = params.get("bucket") ?? "";
  const dir = params.get("dir") ?? "";
  const acct = params.get("acct") ?? "";
  const amin = params.get("amin") ?? "";
  const amax = params.get("amax") ?? "";
  const fix = params.get("fix") === "1";
  const todo = params.get("todo") === "1";
  const sort = params.get("sort") ?? "date";
  const desc = (params.get("dir_sort") ?? "desc") === "desc";

  const [open, setOpen] = useState<Tx | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const [filters, setFilters] = useState(false);
  useEffect(() => { setPicked(new Set()); setAll(false); }, [listQuery]);

  // Load the next page as the end of the list comes into view.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
    }, { rootMargin: "600px" });
    io.observe(node);
    return () => io.disconnect();
  }, [query]);

  const chips = [
    q && { key: "q", label: `« ${q} »` },
    category && { key: "category", label: category },
    acct && { key: "acct", label: first?.accounts.find((a) => a.id === acct)?.label ?? acct },
    bucket && { key: "bucket", label: bucket },
    dir && { key: "dir", label: dir === "out" ? "Sorties" : "Entrées" },
    amin && { key: "amin", label: `≥ ${chf(Number(amin), 0)} CHF` },
    amax && { key: "amax", label: `≤ ${chf(Number(amax), 0)} CHF` },
    fix && { key: "fix", label: "Corrigées" },
    todo && { key: "todo", label: "À classer" },
  ].filter(Boolean) as { key: string; label: string }[];
  const CLEAR = { q: null, category: null, bucket: null, dir: null, amin: null, amax: null, fix: null, todo: null, acct: null };
  const QUICK: { key: string; label: string; on: boolean; patch: Record<string, string | null>; title: string }[] = [
    { key: "todo", label: "À classer", on: todo, patch: { todo: todo ? null : "1" }, title: "non catégorisées, et les Twint sans bénéficiaire" },
    { key: "fix", label: "Corrigées", on: fix, patch: { fix: fix ? null : "1" }, title: "les lignes qu'une épingle ou une règle reclasse" },
    { key: "big", label: "≥ 100 CHF", on: amin === "100", patch: { amin: amin === "100" ? null : "100" }, title: "les montants de 100 CHF et plus" },
    { key: "out", label: "Sorties", on: dir === "out", patch: { dir: dir === "out" ? null : "out" }, title: "les sorties seulement" },
  ];

  const exportHref = (fmt: string) => withQuery(`/export.${fmt}`, nextParams(params, {}, KEEP));
  const toggle = (key: string) => setPicked((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const count = all ? first?.total ?? 0 : picked.size;

  return (
    <div>
      <PageHeader
        title="Transactions"
        subtitle={first ? <>
          {first.period.title} · {plural(first.total, "ligne")} · <span className="num">{chf(first.debit_total, 0)}</span> CHF sortis
          {first.credit_total > 0 && <> · <span className="num">{chf(first.credit_total, 0)}</span> CHF entrés</>}
        </> : " "}
        actions={
          <>
            <a href={exportHref("csv")} download className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"><Download size={15} />CSV</a>
            <a href={exportHref("xlsx")} download className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"><Download size={15} />Excel</a>
          </>
        }
      />

      <div className="sticky top-14 z-20 -mx-4 mb-3 bg-[var(--glass)] px-4 pb-3 pt-1 backdrop-blur-xl sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="flex items-center gap-2">
          <SearchBox value={q} onChange={(v) => set({ q: v || null })} />
          {desktop ? (
            <>
              <FilterSelects categories={first?.categories ?? []} category={category} bucket={bucket} dir={dir} set={set}
                             accounts={first?.accounts ?? []} acct={acct} />
              <AmountRange amin={amin} amax={amax} set={set} compact />
            </>
          ) : (
            <IconButton label="Filtres et tri" onClick={() => setFilters(true)}
                        className={cx("size-11 border border-hairline-2 bg-surface", chips.length > (q ? 1 : 0) && "text-accent")}>
              <SlidersHorizontal size={18} />
            </IconButton>
          )}
          <IconButton label={selecting ? "Terminer la sélection" : "Sélectionner"} onClick={() => { setSelecting(!selecting); setPicked(new Set()); setAll(false); }}
                      className={cx("size-11 border border-hairline-2 bg-surface lg:size-10", selecting && "bg-ink text-page hover:bg-ink hover:text-page")}>
            <ListChecks size={18} />
          </IconButton>
        </div>
        <div className="mt-2 flex gap-1.5 overflow-x-auto no-scrollbar" role="group" aria-label="Filtres rapides">
          {QUICK.map((f) => (
            <button key={f.key} type="button" aria-pressed={f.on} title={f.title} onClick={() => set(f.patch)}
                    className={cx("shrink-0 rounded-full border px-3 py-1 text-[12.5px] font-medium transition",
                      f.on ? "border-transparent bg-ink text-page" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
              {f.label}
            </button>
          ))}
        </div>
        {chips.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {chips.map((c) => (
              <button key={c.key} type="button" onClick={() => set({ [c.key]: null })}
                      className="inline-flex items-center gap-1 rounded-full bg-surface-2 py-1 pl-3 pr-2 text-[12.5px] font-medium hover:bg-surface-3">
                {c.label}<X size={13} className="text-muted" />
              </button>
            ))}
            {chips.length > 1 && (
              <button type="button" onClick={() => set(CLEAR)}
                      className="px-2 text-[12.5px] text-muted hover:text-ink">Tout effacer</button>
            )}
          </div>
        )}
      </div>

      <AnimatePresence>
        {selecting && (
          <BulkBar count={count} total={first?.total ?? 0} all={all} setAll={setAll}
                   onDone={() => { setPicked(new Set()); setAll(false); setSelecting(false); }}
                   target={{ keys: [...picked], filter: nextParams(params, {}, KEEP) }} />
        )}
      </AnimatePresence>

      {first && first.summary && (
        <Summary s={first.summary} filtered={chips.length > 0}
                 onCategory={(name) => set({ category: name })}
                 onPayee={(name) => set({ q: name })} />
      )}

      {!first ? (
        <div className="space-y-2">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-14" />)}</div>
      ) : rows.length === 0 ? (
        <Card className="p-10 text-center text-[14px] text-muted">
          Aucune transaction ne correspond.
          {chips.length > 0 && <div className="mt-3"><Button size="sm" onClick={() => set(CLEAR)}>Effacer les filtres</Button></div>}
        </Card>
      ) : desktop ? (
        <Card className={cx("overflow-hidden", query.isPlaceholderData && "opacity-70")}>
          <DesktopTable rows={rows} slots={first.slots ?? {}} sort={sort} desc={desc} selecting={selecting} picked={picked} all={all}
                        onSort={(key) => set({ sort: key === "date" && sort === "date" && !desc ? null : key,
                          dir_sort: sort === key ? (desc ? "asc" : null) : null })}
                        onToggle={toggle} onOpen={setOpen}
                        onToggleAll={(on) => setPicked(on ? new Set(rows.map((r) => r.key)) : new Set())} />
        </Card>
      ) : (
        <Card className={cx("px-3 py-1", query.isPlaceholderData && "opacity-70")}>
          {sort === "date" ? (
            <TxGroups rows={rows} onOpen={selecting ? (t) => toggle(t.key) : setOpen} sticky
                      leading={selecting ? (t) => <Tick on={all || picked.has(t.key)} onClick={() => toggle(t.key)} /> : undefined} />
          ) : (
            <div className="divide-y divide-hairline">
              {rows.map((t) => (
                <TxRow key={t.key} tx={t} showDate onOpen={selecting ? (x) => toggle(x.key) : setOpen}
                       leading={selecting ? <Tick on={all || picked.has(t.key)} onClick={() => toggle(t.key)} /> : undefined} />
              ))}
            </div>
          )}
        </Card>
      )}

      <div ref={sentinel} className="h-px" />
      {query.isFetchingNextPage && <div className="mt-3 space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>}
      {first && !query.hasNextPage && rows.length > 0 && (
        <p className="py-6 text-center text-[12.5px] text-muted">{plural(first.total, "ligne")} · fin de la liste</p>
      )}

      <TxSheet tx={open} onClose={() => setOpen(null)} />
      <Sheet open={filters} onOpenChange={setFilters} title="Filtres et tri">
        <div className="space-y-5">
          <FilterSelects categories={first?.categories ?? []} category={category} bucket={bucket} dir={dir} set={set}
                             accounts={first?.accounts ?? []} acct={acct} stacked />
          <AmountRange amin={amin} amax={amax} set={set} />
          <div>
            <div className="eyebrow mb-2">Trier par</div>
            <Segmented label="Trier par" value={sort} options={SORTS}
                       onChange={(id) => set({ sort: id === "date" ? null : id })} />
            <div className="mt-2">
              <Segmented label="Ordre" value={desc ? "desc" : "asc"} size="sm"
                         options={[{ id: "desc", label: sort === "date" ? "Récentes d'abord" : "Décroissant" },
                                   { id: "asc", label: sort === "date" ? "Anciennes d'abord" : "Croissant" }]}
                         onChange={(id) => set({ dir_sort: id === "desc" ? null : "asc" })} />
            </div>
          </div>
          <Button variant="primary" size="lg" className="w-full" onClick={() => setFilters(false)}>
            Voir {first ? plural(first.total, "ligne") : "les lignes"}
          </Button>
        </div>
      </Sheet>
    </div>
  );
}

/** Bounds on the size of an amount, in francs, either way. Read when the
 * field is left or Enter pressed -- not on each key, which would refilter
 * on "1" before "150". */
function AmountRange({ amin, amax, set, compact }: {
  amin: string; amax: string; set: (p: Record<string, string | null>) => void; compact?: boolean;
}) {
  const field = (key: "amin" | "amax", label: string, value: string) => (
    <label className={compact ? "block w-24" : "block min-w-0 flex-1"}>
      <span className={compact ? "sr-only" : "eyebrow mb-2 block"}>{label}</span>
      <input key={value} type="number" inputMode="decimal" min="0" step="any" defaultValue={value}
             placeholder={compact ? (key === "amin" ? "dès CHF" : "jusqu'à") : "CHF"}
             onBlur={(e) => { const v = e.target.value.trim(); if (v !== value) set({ [key]: v || null }); }}
             onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
             className={cx("num w-full rounded-xl border border-hairline-2 bg-surface px-3", compact ? "h-10 text-[14px]" : "h-11 text-[16px]")} />
    </label>
  );
  if (compact) return <div className="flex gap-1.5" title="Montant, en francs, entrées comme sorties">{field("amin", "Montant dès", amin)}{field("amax", "Jusqu'à", amax)}</div>;
  return (
    <div>
      <div className="flex gap-3">{field("amin", "Montant dès", amin)}{field("amax", "Jusqu'à", amax)}</div>
      <p className="mt-1.5 text-[12px] text-muted">En francs, entrées comme sorties.</p>
    </div>
  );
}

function Tick({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button type="button" role="checkbox" aria-checked={on} onClick={onClick}
            aria-label={on ? "Désélectionner" : "Sélectionner"}
            className={cx("grid size-6 shrink-0 place-items-center rounded-lg border transition",
              on ? "border-transparent bg-ink text-page" : "border-hairline-2 bg-surface")}>
      {on && <Check size={14} strokeWidth={3} />}
    </button>
  );
}

/** Typing filters as it goes -- a quarter of a second after the last key,
 * replacing the history entry rather than pushing one per letter. */
function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  const latest = useRef(value);
  useEffect(() => { if (value !== latest.current) { setText(value); latest.current = value; } }, [value]);
  useEffect(() => {
    if (text === latest.current) return;
    const t = setTimeout(() => { latest.current = text; onChange(text.trim()); }, 250);
    return () => clearTimeout(t);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <label className="relative min-w-0 flex-1">
      <span className="sr-only">Rechercher</span>
      <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
      <input type="search" value={text} onChange={(e) => setText(e.target.value)}
             placeholder="Bénéficiaire, lieu, montant, date…"
             autoCapitalize="off" autoCorrect="off" spellCheck={false} enterKeyHint="search"
             className="h-11 w-full rounded-xl border border-hairline-2 bg-surface pl-10 pr-3 text-[16px] shadow-[var(--shadow-sm)] outline-none transition focus:border-accent lg:h-10 lg:text-[14px]" />
    </label>
  );
}

function FilterSelects({
  categories, category, bucket, dir, set, stacked, accounts, acct,
}: {
  categories: string[]; category: string; bucket: string; dir: string;
  accounts: { id: string; label: string }[]; acct: string;
  set: (p: Record<string, string | null>) => void; stacked?: boolean;
}) {
  const cls = cx("h-10 rounded-xl border border-hairline-2 bg-surface px-3 text-[14px]", stacked && "h-11 w-full text-[16px]");
  const field = (label: string, el: React.ReactNode) => stacked
    ? <label className="block"><span className="eyebrow mb-2 block">{label}</span>{el}</label>
    : <label><span className="sr-only">{label}</span>{el}</label>;
  return (
    <div className={stacked ? "space-y-4" : "flex items-center gap-2"}>
      {field("Catégorie", (
        <select value={category} onChange={(e) => set({ category: e.target.value || null })} className={cls}>
          <option value="">Toutes les catégories</option>
          {categories.map((c) => <option key={c}>{c}</option>)}
        </select>
      ))}
      {(accounts.length > 1 || acct) && field("Compte", (
        <select value={acct} onChange={(e) => set({ acct: e.target.value || null })} className={cls}>
          <option value="">Tous les comptes</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
      ))}
      {field("Besoin ou envie", (
        <select value={bucket} onChange={(e) => set({ bucket: e.target.value || null })} className={cls}>
          <option value="">Besoins et envies</option>
          {["Need", "Want", "Non classé", "Save"].map((b) => <option key={b} value={b}>{bucketLabel(b)}</option>)}
        </select>
      ))}
      {field("Sens", (
        <select value={dir} onChange={(e) => set({ dir: e.target.value || null })} className={cls}>
          <option value="">Entrées et sorties</option>
          <option value="out">Sorties</option>
          <option value="in">Entrées</option>
        </select>
      ))}
    </div>
  );
}

function DesktopTable({
  rows, slots, sort, desc, selecting, picked, all, onSort, onToggle, onToggleAll, onOpen,
}: {
  rows: Tx[]; slots: Record<string, number>; sort: string; desc: boolean; selecting: boolean; picked: Set<string>; all: boolean;
  onSort: (key: string) => void; onToggle: (key: string) => void; onToggleAll: (on: boolean) => void;
  onOpen: (tx: Tx) => void;
}) {
  const head = (key: string, label: string, right?: boolean) => {
    const active = sort === key;
    return (
      <th scope="col" aria-sort={active ? (desc ? "descending" : "ascending") : "none"}
          className={cx("px-3 py-2.5 text-[11.5px] font-semibold uppercase tracking-[0.06em]", right ? "text-right" : "text-left")}>
        <button type="button" onClick={() => onSort(key)}
                className={cx("inline-flex items-center gap-1 uppercase transition hover:text-ink", active ? "text-ink" : "text-muted")}>
          {label}{active && (desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
        </button>
      </th>
    );
  };
  const allOn = all || (rows.length > 0 && rows.every((r) => picked.has(r.key)));
  return (
    <table className="w-full border-collapse text-[13.5px]">
      <thead className="border-b border-hairline bg-surface-2/40">
        <tr>
          {selecting && (
            <th className="w-10 pl-4"><Tick on={allOn} onClick={() => onToggleAll(!allOn)} /></th>
          )}
          {head("date", "Date")}
          {head("label", "Bénéficiaire")}
          {head("category", "Catégorie")}
          {head("amount", "Montant", true)}
          {head("chf", "En CHF", true)}
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => {
          const on = all || picked.has(t.key);
          return (
            <tr key={t.key} onClick={() => (selecting ? onToggle(t.key) : onOpen(t))}
                className={cx("cursor-pointer border-b border-hairline last:border-0 transition hover:bg-surface-2/60", on && "bg-[color-mix(in_srgb,var(--s0)_7%,transparent)]")}>
              {selecting && <td className="pl-4" onClick={(e) => e.stopPropagation()}><Tick on={on} onClick={() => onToggle(t.key)} /></td>}
              <td className="num whitespace-nowrap px-3 py-2.5 text-ink-2">{frDate(t.date)}</td>
              <td className="max-w-[340px] px-3 py-2.5">
                <div className="truncate font-medium">{t.label}</div>
                {(t.subcategory || t.location || t.account) && (
                  <div className="truncate text-[12px] text-muted">{[t.subcategory, t.location, t.account].filter(Boolean).join(" · ")}</div>
                )}
              </td>
              <td className="px-3 py-2.5">
                <span className="flex flex-wrap gap-1"><Chip><span className="inline-flex items-center gap-1.5">
                  {t.category && <Dot color={slots[t.category] != null ? `var(--s${slots[t.category]})` : "var(--unsorted)"} />}{t.category || "—"}</span></Chip>{t.overridden && <Chip tone="accent">corrigé</Chip>}</span>
              </td>
              <td className="px-3 py-2.5 text-right"><Amount tx={t} className="font-medium" /></td>
              <td className="num px-3 py-2.5 pr-5 text-right text-ink-2">{chf(t.chf)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Reclassify the selection -- or every row of the filter, across pages. */
function BulkBar({
  count, total, all, setAll, onDone, target,
}: {
  count: number; total: number; all: boolean; setAll: (v: boolean) => void; onDone: () => void;
  target: { keys: string[]; filter: URLSearchParams };
}) {
  const { data: choices } = useApi<Choices>("/api/choices");
  const [category, setCategory] = useState("");
  const [bucket, setBucket] = useState("");
  const [applyAs, setApplyAs] = useState<"merchant" | "pin">("pin");
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = Object.fromEntries(target.filter.entries());
      Object.assign(body, { to_category: category, to_bucket: bucket, apply_as: applyAs });
      if (all) body.scope_all = 1;
      else body.keys = target.keys;
      const r = await send<{ count: number; rules: number; merchants: number; undo: unknown }>("/api/reclassify/bulk", body);
      onDone();
      toast.success(`${plural(r.count, "mouvement")} reclassé${r.count > 1 ? "s" : ""}`, {
        description: r.rules ? `${plural(r.rules, "règle")} enregistrée${r.rules > 1 ? "s" : ""} : les prochains suivront.` : undefined,
        action: { label: "Annuler", onClick: async () => { await send("/api/reclassify/bulk/undo", r.undo); toast("Correction annulée"); } },
      });
    } catch (e) {
      toast.error("La correction a échoué", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                className="mb-3 rounded-2xl border border-hairline-2 bg-surface p-3 shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[14px] font-semibold num">{plural(count, "sélectionnée", "sélectionnées")}</span>
        <label className="inline-flex items-center gap-2 text-[13px] text-ink-2">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="size-4 accent-[var(--ink)]" />
          tout le filtre ({total})
        </label>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
        <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="h-10 rounded-xl border border-hairline-2 bg-surface px-3 text-[16px] sm:text-[14px]" aria-label="Catégorie cible">
          <option value="">Catégorie inchangée</option>
          {choices?.categories.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={bucket} onChange={(e) => setBucket(e.target.value)}
                className="h-10 rounded-xl border border-hairline-2 bg-surface px-3 text-[16px] sm:text-[14px]" aria-label="Bloc cible">
          <option value="">Besoin / envie inchangé</option>
          {choices?.buckets.map((b) => <option key={b} value={b}>{bucketLabel(b)}</option>)}
        </select>
        <Segmented size="sm" label="Portée" value={applyAs} onChange={setApplyAs}
                   options={[{ id: "pin", label: "Ces lignes" }, { id: "merchant", label: "+ futurs (règles)" }]} />
        <Button variant="primary" disabled={busy || !count || (!category && !bucket)} onClick={apply}>Appliquer</Button>
      </div>
    </motion.div>
  );
}
