/** The tax still to pay, estimated from the rate actually paid on a past
 * year: on the tax page, and beside the projected cash -- where what the
 * forecast does not already pay is cash that is not free. */
import { Landmark } from "lucide-react";

import { Button, cx } from "@/components/ui";
import { MONTHS, chf, pct } from "@/lib/format";
import type { TaxProvision } from "@/lib/types";

const month = (key: string) => `${MONTHS[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`;

export function TaxReserve({ p, onReserve, className }: { p: TaxProvision; onReserve?: (amount: number) => void; className?: string }) {
  const b = p.basis;
  return (
    <div data-tax-provision className={cx("rounded-2xl border border-hairline p-4", className)}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Landmark size={16} className="self-center text-muted" />
        <span className="text-[14px] font-semibold text-ink">Impôts encore dus</span>
        <span className="num text-[20px] font-semibold tracking-tight">{chf(p.outstanding, 0)} CHF</span>
        <span className="text-[12px] text-muted">estimation</span>
      </div>
      {p.years.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[13px] text-ink-2">
          {p.years.map((y) => (
            <li key={y.year}>
              <b className="text-ink">{y.year}</b> : ≈ {chf(y.estimated, 0)} sur un salaire {y.pay_estimated ? `prévu de ${chf(y.pay, 0)} (${chf(y.pay_so_far, 0)} à ce jour)` : `de ${chf(y.pay, 0)}`}
              {" "}· payé {chf(y.paid, 0)}{y.later ? ` en ${y.paid_in}` : ""} · <span className="font-medium text-ink">reste {chf(y.outstanding, 0)}</span>
            </li>
          ))}
        </ul>
      )}
      {p.uncovered != null && p.until && (
        p.uncovered > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[color-mix(in_srgb,var(--warn)_9%,transparent)] px-3 py-2 text-[13px]">
            <span className="min-w-0 flex-1">
              La prévision n'en paie que {chf(p.planned ?? 0, 0)} d'ici {month(p.until)} :
              {" "}<b className="text-ink">{chf(p.uncovered, 0)} CHF</b> de ton cash ne sont pas libres.
            </span>
            {onReserve && <Button size="sm" onClick={() => onReserve(p.uncovered!)}>Garder en réserve</Button>}
          </div>
        ) : (
          <p className="mt-2 text-[12.5px] text-good">La prévision les paie déjà : {chf(p.planned ?? 0, 0)} CHF d'impôts d'ici {month(p.until)}.</p>
        )
      )}
      <p className="mt-2 text-[12px] leading-relaxed text-muted">
        Taux tiré de {b.year} : {chf(b.tax, 0)} CHF d'impôts payés{b.paid_in !== b.year ? ` en ${b.paid_in}` : ""} sur {chf(b.pay, 0)} de salaire net, soit {pct(b.rate * 100)}.
        Le même taux sur le salaire des années pas encore réglées, moins ce qui est déjà payé. Pas un bordereau : un revenu qui change de tranche, une déduction nouvelle, un acompte le déplacent.
      </p>
    </div>
  );
}
