/** C and E: the month in words -- its review, and why it cost what it did. */
import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { Columns } from "@/charts/Columns";
import { Button, Chip, Track, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { MONTHS_SHORT, chf, frDate } from "@/lib/format";
import type { Tx } from "@/lib/types";
import { useView } from "@/lib/url";
import { useAi, AiBadge, Figures, Sources, useLocalFlag, aiBox, failed } from "./common";

interface WhyAnswer {
  text: string; nature: string; rows: Tx[];
  total: number; median: number; delta: number; label: string;
  months: { mois: string; total: number; current?: boolean }[];
  drift: { category: string; count: number; delta: number }[];
}

/** The categories furthest from their median this month: up in the
 * critical tone, down in the good one, on one scale. */
function Moved({ rows }: { rows: { category: string; now: number; median: number; delta: number }[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.delta)), 1);
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-3.5">
      <h3 className="mb-2 text-[13.5px] font-semibold">Ce qui a changé</h3>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.category} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_4.5rem] items-center gap-2 text-[12.5px]">
            <span className="truncate" title={`${chf(r.now, 0)} ce mois, médiane ${chf(r.median, 0)}`}>{r.category}</span>
            <Track value={(Math.abs(r.delta) / max) * 100} color={r.delta > 0 ? "var(--critical)" : "var(--good)"} />
            <span className={cx("num text-right", r.delta > 0 ? "text-critical" : "text-good")}>{r.delta > 0 ? "+" : "−"}{chf(Math.abs(r.delta), 0)}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11.5px] text-muted">Écarts à la médiane des 12 mois précédents, catégorie par catégorie.</p>
    </div>
  );
}

/** The month among the months before it, against their median. */
function MonthColumns({ answer }: { answer: WhyAnswer }) {
  const label = (key: string) => {
    const [y, m] = key.split("-").map(Number);
    return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
  };
  return (
    <div className="mt-3">
      <Columns
        height={130}
        columns={answer.months.map((m) => ({
          key: m.mois, label: label(m.mois), short: label(m.mois).slice(0, 1), total: m.total,
          segments: [{ name: m.current ? "Ce mois" : "Dépensé", value: m.total, color: m.current ? "var(--s1)" : "var(--unsorted)" }],
        }))}
        reference={answer.median} referenceLabel="médiane"
        ariaLabel={`Dépenses de ${answer.label} et des mois précédents, face à la médiane`}
      />
    </div>
  );
}

const NATURE: Record<string, string> = {
  ponctuel: "quelques lignes ponctuelles", récurrent: "une habitude qui dérive",
  mixte: "ponctuel et habitude", ordinaire: "un mois ordinaire",
};

export function MonthAssist({ first, last }: { first: string; last: string }) {
  const ai = useAi();
  const q = new URLSearchParams({ from: first, to: last });
  const { data: review } = useApi<{
    summary: { headline: string; points: string[] } | null;
    moved: { category: string; now: number; median: number; delta: number }[];
  }>("/api/ai/review", q, !!ai?.enabled);
  const { data: why } = useApi<{ answer: WhyAnswer | null }>("/api/ai/why", q, !!ai?.enabled);
  const [busy, setBusy] = useState<"" | "review" | "why">("");
  const [short, setShort] = useLocalFlag("pms-review-short");
  const [hidden, setHidden] = useLocalFlag(`pms-review-hidden-${first}`);
  const { params, go } = useView();
  const box = useRef<HTMLDivElement>(null);
  // Arrived from "Pourquoi ce mois ?" under the months chart: the click was
  // the question; answer it once, and bring the answer into view.
  const wanted = params.get("why") === "1";
  useEffect(() => {
    if (!wanted || !why || !ai?.enabled) return;
    go({ why: null }, { replace: true });
    box.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (!why.answer) void ask("why");
  }, [wanted, why, ai?.enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ai?.enabled) return null;

  const ask = async (what: "review" | "why", again = false) => {
    setBusy(what);
    try {
      await send(`/api/ai/${what}`, { from: first, to: last, again });
    } catch (e) {
      failed(what === "review" ? "Le bilan n'a pas pu être écrit" : "L'explication n'a pas pu être écrite", e);
    } finally {
      setBusy("");
    }
  };
  const answer = why?.answer;
  const link = "text-[12px] text-muted underline-offset-2 hover:underline disabled:opacity-50";
  return (
    <div ref={box} className="mt-4 scroll-mt-24 space-y-3">
      {review?.summary && hidden && (
        <button type="button" className={link} onClick={() => setHidden(false)}>Afficher le bilan du mois</button>
      )}
      {review?.summary && !hidden ? (
        <div className={aiBox}>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <h3 className="text-[15px] font-semibold">Bilan du mois</h3>
            <AiBadge>résumé</AiBadge>
          </div>
          <p className="text-[15px] leading-relaxed"><Figures text={review.summary.headline} /></p>
          {!short && review.summary.points.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] leading-relaxed text-ink-2 marker:text-muted">
              {review.summary.points.map((p, i) => <li key={i}><Figures text={p} /></li>)}
            </ul>
          )}
          <Sources items={["revue du mois", "médianes des 12 mois", "depuis janvier"]} />
          <div className="mt-2.5 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setShort(!short)}>{short ? "Plus détaillé" : "Plus court"}</Button>
            <Button size="sm" onClick={() => ask("review", true)} disabled={!!busy}>{busy === "review" ? "Réécriture…" : "Réécrire"}</Button>
            <Button size="sm" variant="ghost" onClick={() => setHidden(true)}>Masquer le bilan</Button>
          </div>
        </div>
      ) : null}
      {review?.summary && !hidden && review.moved.length > 0 && <Moved rows={review.moved} />}
      {answer ? <Why answer={answer} /> : null}
      {(!review?.summary || !answer) && (
        <div className="flex flex-wrap gap-2">
          {review && !review.summary && (
            <Button size="sm" onClick={() => ask("review")} disabled={!!busy}>
              <Sparkles size={14} />{busy === "review" ? "Rédaction…" : "Faire le bilan du mois"}
            </Button>
          )}
          {why && !answer && (
            <Button size="sm" onClick={() => ask("why")} disabled={!!busy}>
              <Sparkles size={14} />{busy === "why" ? "Analyse…" : "Pourquoi ce mois ?"}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** E, as sketched: the month among the months before it, the sentence, the
 * lines that carry the gap, and the categories drifting above their median. */
function Why({ answer }: { answer: WhyAnswer }) {
  const shown = new Set(answer.rows.map((t) => t.category));
  const drift = answer.drift.filter((d) => !shown.has(d.category)).slice(0, 2);
  const sign = answer.delta >= 0 ? "+" : "−";
  return (
    <div className={aiBox}>
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <h3 className="text-[15px] font-semibold">
          {answer.label}, <span className="num">{sign}{chf(Math.abs(answer.delta), 0)}</span> {answer.delta >= 0 ? "sur" : "sous"} la médiane
        </h3>
        <AiBadge>explication</AiBadge>
      </div>
      {answer.months.length > 1 && <MonthColumns answer={answer} />}
      <p className="mt-2 text-[14px] leading-relaxed"><Figures text={answer.text} /></p>
      <Chip className="mt-2">{NATURE[answer.nature] ?? answer.nature}</Chip>
      {(answer.rows.length > 0 || drift.length > 0) && (
        <div className="mt-2">
          {answer.rows.map((t) => (
            <div key={t.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-t border-hairline py-2 first:border-t-0">
              <span className="truncate text-[14px] font-medium">{t.label}</span>
              <span className="num text-right text-[14px]">{chf(-t.chf)}</span>
              <Link to={`/jour/${t.date}`} className="col-span-2 text-[12px] text-muted underline-offset-2 hover:underline">
                {frDate(t.date)} · {t.category}{t.currency !== "CHF" ? ` · ${t.currency}` : ""}
              </Link>
            </div>
          ))}
          {drift.map((d) => (
            <div key={d.category} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-t border-hairline py-2">
              <span className="truncate text-[14px] font-medium">{d.category} ({d.count} ligne{d.count > 1 ? "s" : ""})</span>
              <span className="num text-right text-[14px] text-critical">+{chf(d.delta)}</span>
              <span className="col-span-2 text-[12px] text-muted">au-dessus de la médiane de la catégorie</span>
            </div>
          ))}
        </div>
      )}
      <Sources items={["médiane des 12 mois précédents", "plus grosses lignes du mois"]} />
    </div>
  );
}
