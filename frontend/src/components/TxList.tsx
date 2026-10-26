/** Transactions as a list: the phone's table. Grouped by day when sorted by
 * date -- the way a bank app reads -- each row the payee, its category and
 * the amount. A row opens its detail and the reclassification. */
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { chf, frLongDay } from "@/lib/format";
import type { Tx } from "@/lib/types";

import { cx } from "./ui";

export function Initial({ label, tone }: { label: string; tone?: string }) {
  const letter = (label.match(/[A-Za-zÀ-ÿ0-9]/)?.[0] ?? "·").toUpperCase();
  return (
    <span
      aria-hidden
      className="grid size-10 shrink-0 place-items-center rounded-[12px] text-[15px] font-semibold"
      style={tone
        ? { background: `color-mix(in srgb, ${tone} 14%, var(--surface))`, color: tone }
        : { background: "var(--surface-2)", color: "var(--ink-2)" }}
    >
      {letter}
    </span>
  );
}

export function Amount({ tx, className }: { tx: Tx; className?: string }) {
  const income = tx.amount > 0;
  return (
    <span className={cx("num whitespace-nowrap font-semibold", income ? "text-good" : "text-ink", className)}>
      {income ? "+" : ""}{chf(tx.amount)}
      {tx.currency !== "CHF" && <span className="ml-1 text-[11px] font-medium text-muted">{tx.currency}</span>}
    </span>
  );
}

export function TxRow({
  tx, onOpen, leading, showDate,
}: { tx: Tx; onOpen?: (tx: Tx) => void; leading?: ReactNode; showDate?: boolean }) {
  const sub = [tx.category, tx.subcategory].filter(Boolean).join(" · ") || "Non catégorisé";
  return (
    <div className="flex items-center gap-3 px-1 py-2.5">
      {leading}
      <button type="button" onClick={() => onOpen?.(tx)}
              className="flex min-w-0 flex-1 items-center gap-3 rounded-xl text-left">
        <Initial label={tx.label} tone={tx.amount > 0 ? "var(--good)" : undefined} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14.5px] font-medium text-ink">{tx.label}</span>
          <span className="block truncate text-[12.5px] text-muted">
            {showDate ? `${tx.date.slice(8, 10)}.${tx.date.slice(5, 7)}.${tx.date.slice(0, 4)} · ` : ""}
            {sub}{tx.overridden ? " · corrigé" : ""}
          </span>
        </span>
        <span className="flex flex-col items-end">
          <Amount tx={tx} className="text-[14.5px]" />
          {tx.currency !== "CHF" && <span className="num text-[11.5px] text-muted">{chf(tx.chf)} CHF</span>}
        </span>
        {onOpen && <ChevronRight size={16} className="shrink-0 text-axis" />}
      </button>
    </div>
  );
}

/** Rows grouped under a day heading, with the day's net. */
export function TxGroups({
  rows, onOpen, leading, sticky = false,
}: { rows: Tx[]; onOpen?: (tx: Tx) => void; leading?: (tx: Tx) => ReactNode; sticky?: boolean }) {
  const groups: { date: string; rows: Tx[] }[] = [];
  rows.forEach((t) => {
    const last = groups[groups.length - 1];
    if (last && last.date === t.date) last.rows.push(t);
    else groups.push({ date: t.date, rows: [t] });
  });
  return (
    <div>
      {groups.map((g) => {
        const net = g.rows.reduce((s, t) => s + t.chf, 0);
        return (
          <section key={g.date}>
            <h3 className={cx(
              "-mx-1 flex items-center justify-between px-1 pb-1 pt-3 text-[12px] font-semibold text-muted",
              sticky && "sticky top-14 z-10 bg-[var(--glass)] backdrop-blur-md",
            )}>
              <span className="first-letter:uppercase">{frLongDay(g.date)}</span>
              <span className="num font-medium">{chf(net)} CHF</span>
            </h3>
            <div className="divide-y divide-hairline">
              {g.rows.map((t) => (
                <TxRow key={t.key} tx={t} onOpen={onOpen} leading={leading?.(t)} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
