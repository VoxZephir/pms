import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";

import { Num } from "@/components/Num";
import { Spark } from "@/components/Spark";
import { Card, cx } from "@/components/ui";
import { chf } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

function Change({ now, before, goodWhenDown }: { now: number; before: number | undefined; goodWhenDown: boolean }) {
  if (!before) return null;
  const change = ((now - before) / before) * 100;
  const up = change > 0;
  const good = up !== goodWhenDown;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cx(
      "inline-flex items-center gap-0.5 whitespace-nowrap rounded-full px-1.5 py-0.5 font-semibold num",
      good ? "bg-[color-mix(in_srgb,var(--good)_12%,transparent)] text-good"
           : "bg-[color-mix(in_srgb,var(--critical)_12%,transparent)] text-critical",
    )}>
      <Icon size={13} strokeWidth={2.4} />{Math.abs(change).toFixed(1)} %
    </span>
  );
}

function Delta(props: { now: number; before: number | undefined; goodWhenDown: boolean; vs: string }) {
  if (!props.before) return <div className="h-5" />;
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-[12px]" title={`contre ${props.vs} : ${chf(props.before, 0)} CHF`}>
      <Change now={props.now} before={props.before} goodWhenDown={props.goodWhenDown} />
      <span className="truncate text-muted">vs {props.vs}</span>
    </div>
  );
}

/** The tile's figure over the window, in a few points: its shape only. */
export function Kpis({ data }: { data: Dashboard }) {
  const k = data.kpis;
  const p = k.previous ?? undefined;
  const vs = data.previous.label;
  const rows = data.timeline.rows;
  const tiles: { label: string; value: number; delta: ReactNode; note?: ReactNode; tone?: string; signed?: boolean; spark?: ReactNode }[] = [
    { label: "Dépensé", value: k.spend, delta: <Delta now={k.spend} before={p?.spend} goodWhenDown vs={vs} />,
      spark: <Spark values={rows.map((r) => r.spending)} color="var(--critical)" /> },
    { label: "Encaissé", value: k.earn, delta: <Delta now={k.earn} before={p?.earn} goodWhenDown={false} vs={vs} />,
      spark: <Spark values={rows.map((r) => r.income)} color="var(--good)" /> },
    {
      label: "Net", value: k.net, tone: k.net >= 0 ? "text-good" : "text-critical", signed: true,
      delta: <div className="text-[12px] text-muted">{k.net >= 0 ? "mis de côté" : "plus sorti qu'entré"}</div>,
    },
    {
      label: "Par jour", value: k.per_day,
      delta: <Delta now={k.per_day} before={p?.per_day} goodWhenDown vs={vs} />,
      // The mean is dragged up by rent and tax days; the median says what an
      // ordinary day costs -- and whether that moved.
      note: (
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <span className="whitespace-nowrap">médiane {chf(k.median_day, 0)} CHF</span>
          <Change now={k.median_day} before={p?.median_day} goodWhenDown />
        </div>
      ),
    },
    { label: "Solde", value: k.closing, delta: <div className="truncate text-[12px] text-muted">en fin de période, tous comptes</div>,
      spark: <Spark values={data.balance.map(([, v]) => v)} color="var(--s0)" /> },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
      {tiles.map((t, i) => (
        <Card key={t.label} className={cx("flex min-w-0 flex-col gap-1.5 p-4 sm:p-5", i === tiles.length - 1 && "col-span-2 lg:col-span-1")}>
          <div className="eyebrow truncate">{t.label}</div>
          <div className={cx("flex items-baseline gap-1.5 text-[24px] font-semibold leading-none tracking-[-0.03em] sm:text-[28px]", t.tone)}>
            <Num value={t.value} format={(v) => (t.signed && v > 0 ? "+" : "") + chf(v, 0)} className="num" />
            <span className="text-[12px] font-medium tracking-normal text-muted">CHF</span>
          </div>
          <div className="min-h-5">{t.delta}</div>
          {t.note && <div className="text-[12px] text-muted">{t.note}</div>}
          {t.spark}
        </Card>
      ))}
    </div>
  );
}
