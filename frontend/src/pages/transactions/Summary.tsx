/** The filtered rows in brief, above the table: what went out and came in,
 * what a payment usually costs, where the money went, and when. Every
 * figure is the server's (`api/transactions.summary`). */
import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Columns } from "@/charts/Columns";
import { Card, Dot, cx } from "@/components/ui";
import { chf, plural, signedChf } from "@/lib/format";
import type { TxSummary } from "@/lib/types";

const slotColor = (slot: number | null | undefined) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");

export function Summary({ s, onCategory, onPayee, filtered }: {
  s: TxSummary;
  onCategory: (name: string) => void;
  onPayee: (name: string) => void;
  filtered: boolean;
}) {
  const [open, setOpen] = useState(true);
  if (!s.count) return null;
  const figures = [
    { label: "Sorties", value: chf(s.out, 0), sub: plural(s.out_count, "paiement"), tone: "" },
    { label: "Entrées", value: chf(s.in, 0), sub: s.internal ? `${s.internal} entre vos comptes, hors totaux` : "hors virements internes", tone: "" },
    { label: "Solde", value: signedChf(s.net, 0), sub: "entrées − sorties", tone: s.net >= 0 ? "text-good" : "text-critical" },
    { label: "Un paiement", value: s.median != null ? chf(s.median, 0) : "—", sub: "d'habitude (médiane)", tone: "" },
  ];
  const spark = s.series.some((p) => p.out > 0) && s.series.length > 1;
  return (
    <Card className="mb-3 overflow-hidden" aria-label="Ce filtre en bref">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] font-medium text-ink-2 hover:text-ink">
        <span className="eyebrow">{filtered ? "Ce filtre en bref" : "La période en bref"}</span>
        {!open && <span className="num truncate text-muted">{chf(s.out, 0)} sortis · {chf(s.in, 0)} entrés</span>}
        <ChevronDown size={15} className={cx("ml-auto shrink-0 text-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="grid gap-4 border-t border-hairline p-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <div className="grid grid-cols-2 gap-3">
            {figures.map((f) => (
              <div key={f.label} className="min-w-0">
                <div className="eyebrow">{f.label}</div>
                <div className={cx("num mt-0.5 text-[19px] font-semibold tracking-[-0.02em]", f.tone)}>{f.value}</div>
                <div className="truncate text-[11.5px] text-muted">{f.sub}</div>
              </div>
            ))}
          </div>
          {spark ? (
            <div className="min-w-0">
              <div className="eyebrow mb-1">Sorties par {s.grain === "day" ? "jour" : s.grain === "week" ? "semaine" : "mois"}</div>
              <Columns height={110} format={(v) => chf(v, 0)}
                       columns={s.series.map((p) => ({ key: p.key, label: p.label, total: p.out,
                         segments: [{ name: "Sorties", value: p.out, color: "var(--s0)" }] }))}
                       tipRows={(c) => {
                         const p = s.series.find((x) => x.key === c.key)!;
                         return [{ name: "sorties", value: `${chf(p.out, 0)} CHF` }, ...(p.in ? [{ name: "entrées", value: `${chf(p.in, 0)} CHF` }] : [])];
                       }}
                       ariaLabel="Sorties du filtre au fil de la période" />
            </div>
          ) : <div className="hidden lg:block" />}
          <div className="min-w-0">
            {s.parts.length > 0 && (
              <>
                <div className="eyebrow mb-1.5">Où</div>
                <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full" role="img" aria-label="Sorties par catégorie">
                  {s.parts.map((p) => <span key={p.name} style={{ width: `${p.share}%`, background: slotColor(p.slot) }} className="h-full min-w-[2px]" />)}
                </div>
                <ul className="mt-2 space-y-0.5 text-[12.5px]">
                  {s.parts.slice(0, 4).map((p) => (
                    <li key={p.name}>
                      <button type="button" disabled={!!p.rest} onClick={() => onCategory(p.name)}
                              className="flex w-full min-w-0 items-center gap-2 rounded-md px-1 py-0.5 text-left hover:bg-surface-2 disabled:hover:bg-transparent"
                              title={p.rest ? `${p.rest} autres catégories` : `Ne garder que ${p.name}`}>
                        <Dot color={slotColor(p.slot)} /><span className="min-w-0 flex-1 truncate">{p.name}</span>
                        <span className="num text-muted">{Math.round(p.share)} %</span>
                        <span className="num w-16 text-right">{chf(p.amount, 0)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {s.payees.length > 1 && (
              <div className="mt-2 flex flex-wrap gap-1 text-[12px]">
                <span className="text-muted">Surtout :</span>
                {s.payees.slice(0, 3).map((p) => (
                  <button key={p.name} type="button" onClick={() => onPayee(p.name)} title={`${plural(p.count, "paiement")} · ${chf(p.amount, 0)} CHF`}
                          className="max-w-[12rem] truncate rounded-full bg-surface-2 px-2 py-0.5 hover:bg-surface-3">{p.name}</button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
