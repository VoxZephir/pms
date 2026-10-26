/** The Twints the statement leaves blank, one at a time. The amount and the
 * date are all the bank prints: what jogs the memory is the day's other
 * movements and what was decided before at the same amount -- shown, never
 * pre-picked; with enough sorted Twints, a suggestion learned from those
 * decisions, with how often it was right. A category is one tap (or one key, 1-9); swipe the card away to
 * pass; the last choice can be undone. */
import { ArrowLeft, ChevronDown, RotateCcw, SkipForward } from "lucide-react";
import { AnimatePresence, motion, useMotionValue, useTransform, type PanInfo } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/PageState";
import { Select } from "@/components/Form";
import { Button, ButtonLink, Callout, Card, Skeleton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, frDate, frDay, plural } from "@/lib/format";
import { useHotkeys } from "@/lib/hooks";
import type { Tx } from "@/lib/types";
import { useView } from "@/lib/url";

interface Triage {
  queue_size: number; done: number; at: number;
  current: Tx | null; current_key: string; weekday: string | null;
  same_day: Tx[]; hint: [string, number][]; targets: string[]; keys: number;
  groups: { amount: number; count: number; first: string; last: string; keys: string[]; past: [string, number][]; suggested: string }[];
  last: Tx | null; last_key: string;
  suggestions: { category: string; p: number; why: string[] }[];
  measured: Band | null;
  trip: { when: "pendant" | "après"; start: string; end: string; countries: string[]; category: string } | null;
  bands: { band: string; count: number; category: string; examples: number; purity: number; keys: string[]; total: number }[];
}
interface Band {
  band: string; examples: number; top1: number; top3: number; majority: string; purity: number;
  sure_examples: number; sure_top1: number; basis: "band" | "sure";
}

export default function TriagePage() {
  const { params, go } = useView();
  const at = Number(params.get("at") ?? 0) || 0;
  const last = params.get("last") ?? "";
  const q = new URLSearchParams();
  if (at) q.set("at", String(at));
  if (last) q.set("last", last);
  const { data, isPending, error } = useApi<Triage>("/api/triage", q);
  const [dir, setDir] = useState<1 | -1>(1);
  const [busy, setBusy] = useState(false);

  const nav = (patch: { at?: number; last?: string | null }) =>
    go({ at: patch.at ? patch.at : null, last: patch.last ?? null }, { keep: ["at", "last"], replace: true });

  const pin = async (category: string) => {
    if (!data?.current || busy) return;
    setBusy(true);
    setDir(1);
    try {
      const r = await send<{ last: string }>("/api/triage", { action: "pin", key: data.current_key, category });
      nav({ at, last: r.last });
    } catch (e) {
      toast.error("Le classement a échoué", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const skip = () => { if (data && at + 1 < data.queue_size) { setDir(-1); nav({ at: at + 1, last }); } };
  const undo = async () => {
    if (!data?.last) return;
    await send("/api/triage", { action: "undo", key: data.last_key });
    toast("Dernier classement annulé");
    nav({ at, last: null });
  };

  useHotkeys(Object.fromEntries([
    ...(data?.targets.slice(0, data.keys) ?? []).map((c, i) => [String(i + 1), () => void pin(c)]),
    ["s", skip], ["z", () => void undo()],
  ]));

  if (error) return <Callout tone="bad" title="Le tri n'a pas pu être chargé">{error.message}</Callout>;
  if (isPending || !data) return <div className="mx-auto max-w-xl space-y-4"><Skeleton className="h-10 w-56" /><Skeleton className="h-72 rounded-card" /></div>;
  const total = data.queue_size + data.done;
  const c = data.current;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Trier les Twint" eyebrow={<ButtonLink to="/corrections" variant="ghost" size="sm" className="-ml-3"><ArrowLeft size={14} />Corrections</ButtonLink>}
                  subtitle={`${plural(data.queue_size, "à identifier", "à identifier")} · ${data.done} déjà classé${data.done > 1 ? "s" : ""}`} />
      <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <motion.div className="h-full rounded-full bg-s2" initial={false} animate={{ width: `${total ? (data.done / total) * 100 : 0}%` }} />
      </div>

      {data.last && (
        <div className="mb-4 flex items-center gap-3 rounded-2xl border border-hairline bg-surface px-4 py-2.5 text-[13.5px]">
          <span className="min-w-0 flex-1 truncate">{frDate(data.last.date)} · {chf(-data.last.amount)} CHF → <b>{data.last.category}</b></span>
          <Button size="sm" variant="ghost" onClick={undo}><RotateCcw size={14} />Annuler <kbd className="hidden rounded border border-hairline-2 px-1 text-[11px] sm:inline">Z</kbd></Button>
        </div>
      )}

      {c ? (
        <>
          <div className="relative">
            <AnimatePresence mode="popLayout" initial={false} custom={dir}>
              <SwipeCard key={data.current_key} onSkip={skip} dir={dir}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="num text-[44px] font-semibold leading-none tracking-[-0.04em]">{chf(-c.amount)}<span className="ml-1.5 text-[15px] font-medium tracking-normal text-muted">CHF</span></div>
                    <div className="mt-2 text-[15px] text-ink-2"><span className="capitalize">{data.weekday}</span> {frDay(c.date)}</div>
                  </div>
                  <span className="num rounded-full bg-surface-2 px-2.5 py-1 text-[12px] text-muted">{data.at + 1} / {data.queue_size}</span>
                </div>
                {data.trip && <Trip trip={data.trip} />}
                {data.suggestions.length > 0 && data.measured && <Suggestion data={data} />}
                {data.hint.length > 0 && (
                  <p className="mt-4 rounded-xl bg-[color-mix(in_srgb,var(--s0)_8%,transparent)] px-3 py-2 text-[13px]">
                    Déjà classé à ce montant : {data.hint.map(([cat, n], i) => <span key={cat}>{i > 0 && ", "}<b>{cat}</b> ×{n}</span>)}
                  </p>
                )}
                {data.same_day.length > 0 && <SameDay rows={data.same_day} />}
              </SwipeCard>
            </AnimatePresence>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {data.targets.map((cat, i) => {
              const suggested = (data.trip?.category ?? data.suggestions[0]?.category ?? data.hint[0]?.[0]) === cat;
              return (
                <button key={cat} type="button" disabled={busy} onClick={() => pin(cat)}
                        className={cx(
                          "flex min-h-12 items-center gap-2 rounded-2xl border px-3 py-2.5 text-left text-[14px] font-medium transition active:scale-[0.98] disabled:opacity-50",
                          suggested ? "border-transparent bg-ink text-page" : "border-hairline-2 bg-surface hover:bg-surface-2",
                        )}>
                  {i < data.keys && <kbd className={cx("grid size-6 shrink-0 place-items-center rounded-md text-[12px] num", suggested ? "bg-page/20" : "bg-surface-2 text-muted")}>{i + 1}</kbd>}
                  <span className="min-w-0 flex-1 leading-tight">{cat}</span>
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex justify-center">
            <Button variant="ghost" onClick={skip} disabled={at + 1 >= data.queue_size}>
              <SkipForward size={15} />Passer <span className="text-muted">· ou glisser la carte</span>
              <kbd className="hidden rounded border border-hairline-2 px-1 text-[11px] sm:inline">S</kbd>
            </Button>
          </div>
        </>
      ) : (
        <Card className="p-8 text-center">
          <div className="text-[18px] font-semibold">Plus aucun Twint à identifier.</div>
          <p className="mt-1 text-[14px] text-muted">Les suivants arriveront avec le prochain relevé.</p>
        </Card>
      )}

      {data.bands.length > 0 && <Bands data={data} />}
      {data.groups.length > 0 && <Groups data={data} />}
    </div>
  );
}

/** A Twint of a few hundred francs around a stay abroad: the stay jogs the
 * memory, and the owner's convention says where a share of a trip goes. */
function Trip({ trip }: { trip: NonNullable<Triage["trip"]> }) {
  return (
    <p className="mt-4 rounded-xl bg-[color-mix(in_srgb,var(--s3)_12%,transparent)] px-3 py-2 text-[13px]">
      {trip.when === "pendant" ? "Pendant" : "Juste après"} un séjour à l'étranger, du {frDay(trip.start, false)} au {frDay(trip.end)}
      {trip.countries.length > 0 && <> ({trip.countries.join(", ")})</>}. Une part de voyage remboursée se classe en <b>{trip.category}</b>.
    </p>
  );
}

/** What the owner's own past decisions point to -- learned from the Twints
 * already sorted, measured on them, shown and never applied. */
function Suggestion({ data }: { data: Triage }) {
  const [first, ...rest] = data.suggestions;
  const m = data.measured!;
  return (
    <div className="mt-4 rounded-xl bg-[color-mix(in_srgb,var(--s6)_8%,transparent)] px-3 py-2.5 text-[13px]">
      <div>
        Plutôt <b>{first.category}</b> <span className="num text-muted">({Math.round(first.p * 100)} %)</span>
        {rest.length > 0 && <span className="text-ink-2">, sinon {rest.map((r) => r.category).join(" ou ")}</span>}
      </div>
      {first.why.length > 0 && <div className="mt-0.5 text-ink-2">{first.why.join(" · ")}</div>}
      <div className="mt-1 text-[12px] text-muted">
        {m.basis === "sure"
          ? <>Mesuré sur les {m.sure_examples} Twint de {m.band} CHF déjà classés où il était aussi sûr :
              la première idée était la bonne {Math.round(m.sure_top1 * 100)} % du temps.</>
          : <>Mesuré sur tes {m.examples} Twint de {m.band} CHF déjà classés : la première idée était la bonne
              {" "}{Math.round(m.top1 * 100)} % du temps.</>}
      </div>
    </div>
  );
}

function SwipeCard({ children, onSkip, dir }: { children: React.ReactNode; onSkip: () => void; dir: 1 | -1 }) {
  const x = useMotionValue(0);
  const rotate = useTransform(x, [-200, 0, 200], [-6, 0, 6]);
  const opacity = useTransform(x, [-220, 0, 220], [0.4, 1, 0.4]);
  const end = (_: unknown, info: PanInfo) => {
    if (Math.abs(info.offset.x) > 110 || Math.abs(info.velocity.x) > 600) onSkip();
  };
  return (
    <motion.div
      custom={dir}
      style={{ x, rotate, opacity }}
      drag="x"
      dragSnapToOrigin
      dragElastic={0.6}
      onDragEnd={end}
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: dir > 0 ? 0 : -260, y: dir > 0 ? -24 : 0, scale: 0.96, transition: { duration: 0.22 } }}
      className="touch-pan-y cursor-grab rounded-[22px] border border-hairline bg-surface p-5 shadow-card active:cursor-grabbing sm:p-6"
    >
      {children}
    </motion.div>
  );
}

function SameDay({ rows }: { rows: Tx[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-1.5 text-[13px] font-medium text-ink-2">
        <ChevronDown size={14} className={cx("transition-transform", !open && "-rotate-90")} />
        Ce jour-là : {plural(rows.length, "autre mouvement", "autres mouvements")}
      </button>
      {open && (
        <ul className="mt-2 space-y-1 text-[13px]">
          {rows.map((t) => (
            <li key={t.key} className="flex gap-2">
              <span className="min-w-0 flex-1 truncate">{t.label}{t.location && <span className="text-muted"> · {t.location}</span>}</span>
              <span className="num">{chf(t.amount)} {t.currency}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A band where the Twints already sorted were nearly all one category:
 * the rest of the band, in one decision -- shown with that rate, undoable. */
function Bands({ data }: { data: Triage }) {
  const [busy, setBusy] = useState("");
  const apply = async (b: Triage["bands"][number]) => {
    setBusy(b.band);
    try {
      const r = await send<{ restore: unknown }>("/api/triage", { action: "band", keys: b.keys, category: b.category });
      toast.success(`${plural(b.count, "Twint")} de ${b.band} CHF → ${b.category}`, {
        action: { label: "Annuler", onClick: async () => { await send("/api/triage", { action: "restore", restore: r.restore }); toast("Classement annulé"); } },
      });
    } catch (e) {
      toast.error("Le classement a échoué", { description: (e as Error).message });
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="mt-8">
      <h2 className="px-1 text-[17px] font-semibold tracking-tight">Par tranche de montant</h2>
      <p className="px-1 text-[12.5px] text-muted">Là où tes classements sont presque tous la même catégorie : le reste de la tranche en une décision, annulable.</p>
      <div className="mt-3 space-y-2">
        {data.bands.map((b) => (
          <Card key={b.band} className="flex flex-wrap items-center gap-3 p-3.5">
            <div className="min-w-[180px] flex-1">
              <div className="text-[16px] font-semibold"><span className="num">{b.count}</span> Twint de {b.band} CHF</div>
              <div className="text-[12.5px] text-muted">
                Sur tes {b.examples} déjà classés dans cette tranche, {Math.round(b.purity * 100)} % étaient {b.category}.
              </div>
            </div>
            <Button variant="primary" disabled={!!busy} onClick={() => apply(b)}>
              {busy === b.band ? "Classement…" : `Tout en ${b.category}`}
            </Button>
          </Card>
        ))}
      </div>
    </section>
  );
}

function Groups({ data }: { data: Triage }) {
  return (
    <section className="mt-8">
      <h2 className="px-1 text-[17px] font-semibold tracking-tight">Par montant</h2>
      <p className="px-1 text-[12.5px] text-muted">Un montant qui revient est une seule décision : {plural(data.groups.length, "montant récurrent", "montants récurrents")}.</p>
      <div className="mt-3 space-y-2">
        {data.groups.map((g) => <Group key={g.amount} g={g} targets={data.targets} />)}
      </div>
    </section>
  );
}

function Group({ g, targets }: { g: Triage["groups"][number]; targets: string[] }) {
  const [category, setCategory] = useState(g.suggested);
  const [busy, setBusy] = useState(false);
  const apply = async () => {
    setBusy(true);
    try {
      const r = await send<{ restore: unknown }>("/api/triage", { action: "group", keys: g.keys, category });
      toast.success(`${g.count} Twint de ${chf(g.amount)} CHF → ${category}`, {
        action: { label: "Annuler", onClick: async () => { await send("/api/triage", { action: "restore", restore: r.restore }); toast("Classement annulé"); } },
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="flex flex-wrap items-center gap-3 p-3.5">
      <div className="min-w-[140px] flex-1">
        <div className="num text-[16px] font-semibold">{chf(g.amount)} CHF <span className="text-[13px] font-medium text-muted">× {g.count}</span></div>
        <div className="num text-[12px] text-muted">{frDate(g.first)} → {frDate(g.last)}
          {g.past.length > 0 && <> · déjà : {g.past.map(([c, n]) => `${c} ×${n}`).join(", ")}</>}</div>
      </div>
      <div className="flex w-full gap-2 sm:w-auto">
        <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={`Catégorie pour les ${g.count} Twint de ${chf(g.amount)} CHF`} className="flex-1 sm:w-48">
          <option value="">—</option>
          {targets.map((t) => <option key={t}>{t}</option>)}
        </Select>
        <Button variant="primary" disabled={!category || busy} onClick={apply}>Classer les {g.count}</Button>
      </div>
    </Card>
  );
}
