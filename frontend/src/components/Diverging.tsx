/** Before and after, one row per thing, on one scale: a bar to the right is
 * a rise (in red: it cost more), to the left a fall. The amounts are the
 * server's; this draws them. */
import { Link } from "react-router";

import { Dot, cx } from "@/components/ui";
import { chf, signedChf } from "@/lib/format";

export interface DivergingRow { key: string; label: string; before: number; now: number; delta: number; color: string; to?: string }

export function Diverging({ rows, ariaLabel }: { rows: DivergingRow[]; ariaLabel: string }) {
  const top = Math.max(...rows.map((r) => Math.abs(r.delta)), 1);
  return (
    <ul className="space-y-1" aria-label={ariaLabel}>
      {rows.map((r) => {
        const w = (Math.abs(r.delta) / top) * 50;
        const up = r.delta > 0;
        const inner = (
          <>
            <span className="flex min-w-0 items-center gap-2"><Dot color={r.color} /><span className="truncate">{r.label}</span></span>
            <span className="relative h-4" title={`${chf(r.before, 0)} → ${chf(r.now, 0)} CHF`}>
              <span className="absolute inset-y-0 left-1/2 w-px bg-hairline-2" />
              <span className="absolute inset-y-[2px] rounded-[3px]"
                    style={{ left: up ? "50%" : `${50 - w}%`, width: `${Math.max(w, 0.6)}%`,
                             background: up ? "var(--critical)" : "var(--good)", opacity: 0.8 }} />
            </span>
            <span className="text-right">
              <b className={cx("num", up ? "text-critical" : r.delta < 0 ? "text-good" : "")}>{signedChf(r.delta, 0)}</b>
              <span className="num hidden text-[11.5px] text-muted sm:inline"> · {chf(r.before, 0)} → {chf(r.now, 0)}</span>
            </span>
          </>
        );
        const cls = "grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_5rem] items-center gap-3 rounded-lg px-1 py-1 text-[13px] sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_9.5rem]";
        return (
          <li key={r.key}>
            {r.to ? <Link to={r.to} preventScrollReset className={cx(cls, "hover:bg-surface-2/60")}>{inner}</Link>
              : <div className={cls}>{inner}</div>}
          </li>
        );
      })}
    </ul>
  );
}
