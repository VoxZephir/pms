/** The dashboard: one window, every panel that has something to say on it. */
import { HeartPulse, Inbox, PiggyBank, Sparkles, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { DaySheet } from "@/components/DaySheet";
import { PageHeader } from "@/components/PageState";
import { TxGroups } from "@/components/TxList";
import { TxSheet } from "@/components/TxSheet";
import { ButtonLink, Callout, Card, Panel, Skeleton, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { chf, frDate, pct, plural } from "@/lib/format";
import { useDesktop, useStored } from "@/lib/hooks";
import type { Dashboard, Meta, Tx, TxPage } from "@/lib/types";
import { useView } from "@/lib/url";
import { UpdateNotice } from "@/shell/Update";

import { Pace, Soon, Versus } from "./dashboard/Glance";
import { Kpis } from "./dashboard/Kpis";
import {
  Balance, Calendar, Countries, Custodian, Fixed, Highlights, Income, Merchants, Missing, Monthly,
  Profiles, Review, Shares, Years,
} from "./dashboard/Panels";
import { Buckets, Categories } from "./dashboard/Spending";
import { Timeline } from "./dashboard/Timeline";

export function DashboardPage() {
  const { query } = useView();
  const { data, isPending, isPlaceholderData, error } = useApi<Dashboard>("/api/dashboard", query);
  const { data: meta } = useApi<Meta>("/api/meta");
  const [dayOpen, setDayOpen] = useState<string | null>(null);

  if (error) return <Callout tone="bad" title="Le tableau de bord n'a pas pu être chargé">{String(error.message)}</Callout>;
  if (isPending || !data) return <DashboardSkeleton />;
  if (data.empty) return <EmptyLedger meta={meta} />;

  const p = data.period;
  const grain = p.grains.find((g) => g.id === p.grain)?.label.toLowerCase();
  const panels = data.panels;

  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <PageHeader
        title={p.title}
        subtitle={<>
          {frDate(p.start)} → {frDate(p.end)} · {plural(p.days, "jour")} · {plural(data.count, "mouvement")} · par {grain}
          {data.previous.exists && <span className="hidden sm:inline"> · comparé au {frDate(data.previous.start)} → {frDate(data.previous.end)}</span>}
        </>}
      />

      <div className="space-y-4 sm:space-y-5">
        <Notices data={data} meta={meta} />
        <Kpis data={data} />
        {data.pace && <Pace data={data} />}
        {data.soon && data.soon.next.length > 0 && <Soon data={data} />}
        {panels.review && data.review && <Review data={data} />}
        {data.timeline.rows.length > 0 && <Timeline data={data} onDay={setDayOpen} />}
        <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
          <Categories data={data} />
          <Buckets data={data} />
        </div>
        {data.versus.length > 0 && <Versus data={data} />}
        {panels.shares && <Shares data={data} />}
        {p.days >= 7 && Object.keys(data.daily).length > 0 && <Calendar data={data} onDay={setDayOpen} />}
        <Merchants data={data} />
        {panels.balance && <Balance data={data} />}
        {panels.highlights && data.highlights.length > 0 && <Highlights data={data} />}
        {panels.income && data.income && <Income data={data} />}
        {panels.missing && <Missing data={data} />}
        {panels.fixed && data.fixed && <Fixed data={data} />}
        {panels.monthly && <Monthly data={data} />}
        {panels.years && <Years data={data} />}
        <Profiles data={data} />
        {panels.season && panels.country && <Countries data={data} />}
        {panels.custodian && <Custodian data={data} />}
        <Recent />
      </div>
      <DaySheet day={dayOpen} onChange={setDayOpen} />
    </div>
  );
}

/** What wants attention, in one card: a new statement to read, one that is
 * late, a missing backup, a gap in the balances. One row each, its action
 * beside it -- three stacked callouts pushed the figures below the fold. */
function Notices({ data, meta }: { data: Dashboard; meta?: Meta }) {
  const { href } = useView();
  const [dismissed, setDismissed] = useStored<string[]>("pms-news-dismissed", []);
  const news = meta?.news;
  const desktop = useDesktop();
  const showNews = news && !dismissed.includes(news.id) && !(news.start === data.period.start && news.end === data.period.end);
  const rows: { key: string; icon: ReactNode; tone: string; title: ReactNode; detail: ReactNode; action?: ReactNode }[] = [];
  if (meta?.backup) {
    rows.push({ key: "backup", icon: <TriangleAlert size={17} />, tone: "text-critical", title: meta.backup.title,
      detail: <>{meta.backup.detail}. Corrections, règles et plans de <code>data/</code> ne se reconstruisent pas depuis les relevés.</> });
  }
  if (meta && meta.gaps.length > 0) {
    rows.push({ key: "gaps", icon: <TriangleAlert size={17} />, tone: "text-warn", title: "Historique incomplet",
      // A break inside one day is not a hole: two exports ordered that day
      // differently (one downloaded during it). Re-reading them fixes it.
      detail: meta.gaps[0].after === meta.gaps[0].before
        ? <>{plural(meta.gaps.length, "rupture")} dans les soldes le {frDate(meta.gaps[0].after)} : deux relevés ordonnent cette journée différemment, ou le même mouvement y est entré deux fois. Le bouton ⟳ en haut, ou <code>.\run.bat</code>, le répare ; s'il reste, <code>.\run.bat --reparse</code>.</>
        : <>{plural(meta.gaps.length, "rupture")} dans les soldes : des mouvements manquent entre le {frDate(meta.gaps[0].after)} et le {frDate(meta.gaps[0].before)}.</> });
  }
  if (meta?.floor) {
    rows.push({ key: "floor", icon: <TriangleAlert size={17} />, tone: "text-warn", title: "Cash projeté sous ton seuil",
      detail: <>{meta.floor.text} Le plan de Prévisions, sur un an.</>,
      action: <Link to="/previsions" className="shrink-0 rounded-lg border border-hairline-2 px-2.5 py-1 text-[12.5px] font-medium no-underline hover:bg-surface-2">Prévisions</Link> });
  }
  if (meta?.pillar3a) {
    const p = meta.pillar3a;
    rows.push({ key: "pillar3a", icon: <PiggyBank size={17} />, tone: "text-s2",
      title: p.left >= 1 ? `3a ${p.year} : ${chf(p.left, 0)} CHF encore déductibles` : `3a ${p.year} : rachat possible, jusqu'à ${chf(p.room, 0)} CHF`,
      detail: <>{p.text} Compter quelques jours de virement.</>,
      action: <Link to="/impots" className="shrink-0 rounded-lg border border-hairline-2 px-2.5 py-1 text-[12.5px] font-medium no-underline hover:bg-surface-2">Impôts</Link> });
  }
  for (const l of meta?.late ?? []) {
    rows.push({ key: `late-${l.bank}`, icon: <Inbox size={17} />, tone: "text-warn", title: `Relevé ${l.bank} attendu`,
      detail: <>le dernier va jusqu'au {frDate(l.until)}, il y a {l.days} jours · {meta?.watching ? "téléchargé sur le PC, il entre tout seul" : "à envoyer depuis Importer"}</>,
      action: <span className="flex shrink-0 gap-1.5">
        {l.url && <a href={l.url} target="_blank" rel="noopener noreferrer" className="rounded-lg border border-hairline-2 px-2.5 py-1 text-[12.5px] font-medium hover:bg-surface-2">Télécharger ↗</a>}
        <Link to="/importer" className="rounded-lg px-2.5 py-1 text-[12.5px] font-medium text-muted hover:bg-surface-2 hover:text-ink">Importer</Link>
      </span> });
  }
  for (const d of data.soon?.deadlines ?? []) {
    rows.push({ key: `deadline-${d.label}`, icon: <HeartPulse size={17} />, tone: "text-warn", title: d.title,
      detail: <>avant le {frDate(d.by)}, dans {plural(d.days, "jour")}{d.price && d.price.delta > 0 ? ` · ${d.label} a augmenté de ${pct(d.price.pct)} cette année` : ""}</>,
      action: <Link to="/a-venir" className="rounded-lg border border-hairline-2 px-2.5 py-1 text-[12.5px] font-medium no-underline hover:bg-surface-2">Voir</Link> });
  }
  if (showNews && news) {
    rows.push({ key: "news", icon: <Sparkles size={17} />, tone: "text-good", title: "Nouveau relevé",
      detail: <>importé le {frDate(news.when)} : {plural(news.added, "mouvement")} jusqu'au {frDate(news.until)}</>,
      action: <span className="flex shrink-0 items-center gap-1.5">
        <Link to={href({ from: news.start, to: news.end, grain: "auto" })} className="rounded-lg border border-hairline-2 px-2.5 py-1 text-[12.5px] font-medium hover:bg-surface-2">Revue de {news.label}</Link>
        <button type="button" className="rounded-lg px-2 py-1 text-[12.5px] text-muted hover:text-ink" onClick={() => setDismissed([...dismissed, news.id])}>Masquer</button>
      </span> });
  }
  return (
    <>
      {rows.length > 0 && (
        <Card className="divide-y divide-hairline" aria-label="À faire" data-notices>
          {rows.map((r) => (
            <div key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap">
              <span className={cx("shrink-0", r.tone)}>{r.icon}</span>
              <div className="min-w-0 flex-1 basis-[calc(100%-2.5rem)] text-[13px] sm:basis-auto">
                <b className="text-ink">{r.title}</b>
                <span className="text-muted"> · {r.detail}</span>
              </div>
              {r.action && <div className="w-full pl-8 sm:w-auto sm:pl-0">{r.action}</div>}
            </div>
          ))}
        </Card>
      )}
      {!desktop && <UpdateNotice />}
      {data.count === 0 && (
        <Callout tone="warn" title="Aucun mouvement sur cette période">
          Le relevé court du {frDate(data.period.bounds.low)} au {frDate(data.period.bounds.high)}.{" "}
          <Link to={href({ preset: "12m", grain: "auto" })} className="underline">Revenir aux 12 derniers mois</Link>.
        </Callout>
      )}
    </>
  );
}

function Recent() {
  const { params, pageHref } = useView();
  const q = new URLSearchParams();
  for (const k of ["from", "to", "preset"]) { const v = params.get(k); if (v) q.set(k, v); }
  q.set("per", "20");
  const { data } = useApi<TxPage>("/api/transactions", q);
  const [open, setOpen] = useState<Tx | null>(null);
  if (!data || !data.rows.length) return null;
  return (
    <Panel id="tx" title="Dernières transactions" hint={`${data.total} sur la période`}
           actions={<ButtonLink size="sm" to={pageHref("/transactions")}>Tout voir</ButtonLink>}>
      <TxGroups rows={data.rows.slice(0, 10)} onOpen={setOpen} />
      <TxSheet tx={open} onClose={() => setOpen(null)} />
    </Panel>
  );
}

function EmptyLedger({ meta }: { meta?: Meta }) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <Inbox className="mx-auto text-muted" size={36} />
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Aucun relevé pour l'instant</h1>
      <p className="mt-2 text-[14.5px] text-muted">
        Le ledger ({meta?.ledger}) est vide. Envoyer un relevé le remplit.
      </p>
      <ButtonLink to="/importer" variant="primary" size="lg" className="mt-6">Importer un relevé</ButtonLink>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-28 rounded-card" />)}
      </div>
      <Skeleton className="h-80 rounded-card" />
      <div className="grid gap-5 lg:grid-cols-2">
        <Skeleton className="h-72 rounded-card" />
        <Skeleton className="h-72 rounded-card" />
      </div>
    </div>
  );
}
