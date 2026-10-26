/** From one total to another, one step per cause: a waterfall laid out in
 * rows, readable at phone width. The amounts are the server's; the running
 * position of each bar is geometry only. */
import { cx } from "@/components/ui";
import { chf, signedChf } from "@/lib/format";

export interface BridgeStep { key: string; label: string; amount: number; color: string; title?: string }

export function Bridge({ start, steps, end, ariaLabel }: {
  start: { label: string; value: number };
  steps: BridgeStep[];
  end: { label: string; value: number };
  ariaLabel: string;
}) {
  const rows: { key: string; label: string; from: number; to: number; color: string; total?: boolean; title?: string }[] = [];
  let running = start.value;
  rows.push({ key: "start", label: start.label, from: 0, to: start.value, color: "var(--ink-2)", total: true });
  steps.forEach((s) => {
    if (Math.abs(s.amount) < 0.5) return;
    rows.push({ key: s.key, label: s.label, from: running, to: running + s.amount, color: s.color, title: s.title });
    running += s.amount;
  });
  rows.push({ key: "end", label: end.label, from: 0, to: end.value, color: "var(--ink)", total: true });
  const lo = Math.min(0, ...rows.flatMap((s) => [s.from, s.to]));
  const hi = Math.max(...rows.flatMap((s) => [s.from, s.to]), 1);
  const at = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return (
    <ol className="space-y-1.5" aria-label={ariaLabel}>
      {rows.map((s) => {
        const left = at(Math.min(s.from, s.to));
        const width = Math.max(at(Math.max(s.from, s.to)) - left, 0.4);
        const delta = s.to - s.from;
        return (
          <li key={s.key} title={s.title}
              className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_5.5rem] items-center gap-3 text-[13px] sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_6.5rem]">
            <span className={cx("truncate", s.total && "font-semibold")} title={s.label}>{s.label}</span>
            <div className="relative h-4">
              <span className="absolute inset-y-0 rounded-[4px]" style={{ left: `${left}%`, width: `${width}%`, background: s.color, opacity: s.total ? 0.85 : 0.75 }} />
            </div>
            <span className={cx("num text-right", s.total ? "font-semibold" : delta >= 0 ? "text-good" : "text-critical")}>
              {s.total ? chf(s.to, 0) : signedChf(delta, 0)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
