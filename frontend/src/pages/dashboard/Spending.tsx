/** Where the money went: by category (each one unfolding on its sub-posts
 * and payees), and as needs / wants / savings. */
import { ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router";

import { ButtonLink, Dot, Note, Panel, Track, cx } from "@/components/ui";
import { bucketLabel, chf, pct, plural } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { useView } from "@/lib/url";

export function Categories({ data }: { data: Dashboard }) {
  const { pageHref } = useView();
  const [open, setOpen] = useState<string | null>(null);
  const top = data.categories[0]?.amount || 1;
  const win = { from: data.period.start, to: data.period.end };
  return (
    <Panel title="Où part l'argent" hint={plural(data.categories.length, "catégorie")}>
      {data.categories.length === 0 && <p className="text-[14px] text-muted">Aucune dépense sur cette période.</p>}
      <ul className="-mx-2 space-y-0.5">
        {data.categories.map((c) => {
          const isOpen = open === c.category;
          return (
            <li key={c.category}>
              <button type="button" onClick={() => setOpen(isOpen ? null : c.category)} aria-expanded={isOpen}
                      className="grid w-full grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1.5 rounded-xl px-2 py-2 text-left transition hover:bg-surface-2 sm:grid-cols-[14px_minmax(110px,180px)_minmax(0,1fr)_auto_52px]">
                <ChevronRight size={14} className={cx("text-muted transition-transform", isOpen && "rotate-90")} />
                <span className="flex min-w-0 items-center gap-2">
                  <Dot color={`var(--s${c.slot})`} />
                  <span className="truncate text-[14px] font-medium">{c.category}</span>
                </span>
                <Track value={(c.amount / top) * 100} color={`var(--s${c.slot})`} className="col-span-2 col-start-2 row-start-2 sm:col-span-1 sm:col-start-auto sm:row-start-auto" />
                <span className="num text-right text-[13.5px] font-semibold">{chf(c.amount, 0)}</span>
                <span className="num hidden text-right text-[12.5px] text-muted sm:block">{pct(c.share)}</span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                    <div className="grid gap-4 px-2 pb-3 pl-8 pt-1 sm:grid-cols-2">
                      <MiniTable title="Sous-postes" rows={c.subcategories} />
                      <MiniTable title="Principaux bénéficiaires" rows={c.top_merchants}
                                 href={(name) => pageHref("/transactions", { ...win, q: name })} />
                      <div className="sm:col-span-2">
                        <ButtonLink size="sm" to={pageHref("/transactions", { ...win, category: c.category })}>
                          {c.count > 1 ? `Voir les ${c.count} transactions` : "Voir la transaction"}
                        </ButtonLink>
                        <span className="ml-3 text-[12.5px] text-muted">moyenne {chf(c.average)} CHF · {pct(c.share)} des dépenses</span>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function MiniTable({ title, rows, href }: {
  title: string; rows: { name: string; amount: number; count: number }[]; href?: (name: string) => string;
}) {
  return (
    <div>
      <div className="eyebrow mb-1.5">{title}</div>
      <ul className="space-y-1 text-[13px]">
        {rows.map((r) => (
          <li key={r.name} className="flex items-baseline gap-2">
            {href
              ? <Link to={href(r.name)} className="min-w-0 flex-1 truncate text-ink-2 underline-offset-2 hover:text-ink hover:underline">{r.name}</Link>
              : <span className="min-w-0 flex-1 truncate text-ink-2">{r.name || "—"}</span>}
            <span className="num whitespace-nowrap">{chf(r.amount, 0)} <span className="text-muted">· {r.count}×</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Buckets({ data }: { data: Dashboard }) {
  const { pageHref } = useView();
  const b = data.buckets;
  const fill = data.bucket_fill;
  const of = b.basis === "income" ? "des revenus" : "des sorties";
  const link = (name: string) => pageHref("/transactions", { from: data.period.start, to: data.period.end, bucket: name, dir: "out" });
  const parts = b.rows.flatMap((r) => (r.parts.length ? r.parts.map((p) => ({ ...p, bucket: r.name })) : r.share > 0 ? [{ ...r, hollow: false, bucket: r.name }] : []));
  return (
    <Panel title="Besoins, envies, épargne" hint={`en part ${of}`}>
      <div className="flex h-9 w-full gap-[3px] overflow-hidden rounded-xl" role="img"
           aria-label={b.rows.map((r) => `${bucketLabel(r.name)} ${r.share.toFixed(1)} %`).join(", ")}>
        {parts.map((p) => (
          <motion.div key={`${p.bucket}-${p.name}`} initial={false}
                      animate={{ width: `${Math.max(0, p.share)}%` }}
                      transition={{ type: "spring", stiffness: 220, damping: 30 }}
                      title={`${bucketLabel(p.bucket)}${p.name !== p.bucket ? ` — ${p.name}` : ""} : ${pct(p.share)} · ${chf(p.amount, 0)} CHF`}
                      className={cx("h-full min-w-[3px] first:rounded-l-xl last:rounded-r-xl", p.hollow && "hatch")}
                      style={p.hollow
                        ? { color: fill[p.bucket], boxShadow: `inset 0 0 0 1.5px ${fill[p.bucket]}`, opacity: 0.8 }
                        : { background: fill[p.bucket] }} />
        ))}
      </div>
      <ul className="mt-4 space-y-0.5">
        {b.rows.map((r) => (
          <li key={r.name}>
            <Link to={link(r.name)}
                  className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 rounded-xl px-2 py-2 text-[14px] no-underline transition hover:bg-surface-2 -mx-2">
              <Dot color={fill[r.name]} />
              <span className="font-medium">{bucketLabel(r.name)} <span className="text-[12px] font-normal text-muted">{r.count}×</span></span>
              <span className="num text-[12.5px] text-muted">{pct(r.share)}</span>
              <span className="num w-24 text-right font-semibold">{chf(r.amount, 0)}</span>
            </Link>
            {r.parts.length > 1 && r.parts.map((p) => (
              <div key={p.name} className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 py-1 pl-6 text-[13px] text-ink-2">
                <Dot color={fill[r.name]} hollow={p.hollow} />
                <span>{p.name}</span>
                <span className="num text-[12px] text-muted">{pct(p.share)}</span>
                <span className="num w-24 text-right">{chf(p.amount, 0)}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
      <Note>
        {b.basis === "spend"
          ? <>Plus de sorties que de revenus sur cette période : {chf(b.overspend, 0)} CHF de plus que les {chf(b.income, 0)} CHF encaissés, souvent un mois dont le salaire n'est pas encore arrivé. Les parts sont donc prises sur ce qui est sorti ({chf(b.base, 0)} CHF).</>
          : <>En part des revenus de la période ({chf(b.income, 0)} CHF) : les quatre blocs totalisent 100 %.</>}
        {b.residual > 0 && (b.transferred_to_savings > 0
          ? <> L'épargne se lit en deux temps : {chf(b.transferred_to_savings, 0)} CHF versés vers un placement, et {chf(b.residual, 0)} CHF restés sur le compte.</>
          : <> Aucun versement vers un placement : les {chf(b.residual, 0)} CHF d'épargne sont du solde non dépensé, resté sur le compte.</>)}
      </Note>
      {data.panels.shares && (
        <a href="#p-shares" className="mt-2 inline-block text-[13px] font-medium text-accent">Voir l'évolution mois par mois ↓</a>
      )}
    </Panel>
  );
}
