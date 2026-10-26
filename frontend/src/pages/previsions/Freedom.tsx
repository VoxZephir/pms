/** Financial independence: the years of spending the wealth already covers,
 * the wealth that would cover them for good, and when the plan gets there.
 * Figures from `freedom.py`. */
import { Mountain } from "lucide-react";

import { Note, Panel, Segmented, cx } from "@/components/ui";
import { chf, frDate } from "@/lib/format";
import { PREVISIONS_KEEP, type Freedom } from "@/lib/previsions";
import { useView } from "@/lib/url";

const pctLabel = (v: number) => `${String(v).replace(".", ",")} %`;

export function Independence({ f }: { f: Freedom }) {
  const { href } = useView();
  const tiles = [
    { label: "Déjà couvert", value: f.years_label, sub: `de dépense, à ${chf(f.spend, 0)} CHF par an` },
    { label: "L'objectif", value: `${chf(f.target, 0)}`, sub: `CHF, la dépense ÷ ${pctLabel(f.withdrawal)}` },
    { label: "Mis de côté", value: `${chf(f.monthly, 0)}`, sub: "CHF par mois, revenu moins dépense" },
  ];
  return (
    <Panel id="p-freedom" title="L'indépendance financière"
           hint="quand ce que tu as couvrirait ta dépense pour de bon"
           actions={<Segmented size="sm" label="Taux de retrait" value={f.withdrawal}
                               options={f.rates.map((r) => ({ id: r, label: pctLabel(r) }))}
                               hrefFor={(r) => href({ swr: r === 4 ? null : String(r) }, { keep: PREVISIONS_KEEP })} />}>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="min-w-0">
            <div className="eyebrow">{t.label}</div>
            <div className="num mt-1 text-[20px] font-semibold tracking-[-0.02em]">{t.value}</div>
            <div className="truncate text-[12px] text-muted">{t.sub}</div>
          </div>
        ))}
        <div className="min-w-0">
          <div className="eyebrow">Atteint</div>
          {f.declared ? (
            <>
              <div className="num mt-1 text-[20px] font-semibold tracking-[-0.02em]">{f.wait ?? "pas avant 50 ans"}</div>
              <div className="truncate text-[12px] text-muted">{f.date ? `vers ${frDate(f.date).slice(3)}, au rendement déclaré` : "au rendement déclaré"}</div>
            </>
          ) : (
            <>
              <div className="num mt-1 text-[20px] font-semibold tracking-[-0.02em]">{f.wait_flat ?? "pas avant 50 ans"}</div>
              <div className="text-[12px] text-muted">sans rendement · <a href="#p-rates" className="text-accent">déclarer un taux</a></div>
            </>
          )}
        </div>
      </div>
      <div className="mt-4">
        <div className="relative h-3 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${f.progress.toFixed(0)} % de l'objectif`}>
          <div className="h-full rounded-full bg-[var(--good)]" style={{ width: `${Math.max(f.progress, 1)}%` }} />
        </div>
        <div className="mt-1 flex justify-between text-[12px] text-muted">
          <span className="inline-flex items-center gap-1"><Mountain size={13} />{chf(f.wealth, 0)} CHF aujourd'hui</span>
          <span className="num">{f.progress.toFixed(f.progress < 10 ? 1 : 0).replace(".", ",")} % du chemin</span>
        </div>
      </div>
      {f.what_ifs.some((w) => w.wait) && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-3">
          {f.what_ifs.map((w) => (
            <li key={w.label} className="rounded-2xl border border-hairline p-3 text-[13px]">
              <div className="text-ink-2">{w.label}</div>
              <div className="mt-1 font-semibold">{w.wait ?? "pas avant 50 ans"}</div>
              <div className={cx("text-[12px]", w.sooner_label ? "text-good" : "text-muted")}>{w.sooner_label ?? "—"}</div>
            </li>
          ))}
        </ul>
      )}
      <Note>
        Le patrimoine compte tout : compte courant, courtage, 3a et crypto. La dépense est celle des douze derniers mois entiers,
        hors virements d'épargne. Le taux de retrait est une convention : 4 % a tenu sur trente ans dans les études américaines,
        3 à 3,5 % est plus prudent pour un horizon plus long. Les montants sont en francs d'aujourd'hui : un taux déclaré
        net d'inflation (réel) garde la comparaison juste.
      </Note>
    </Panel>
  );
}
