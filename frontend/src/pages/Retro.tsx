/** The year in review: a year told in a dozen findings, one card each --
 * what came in and went out, the dearest month and why, what grew and what
 * shrank, the shops, the countries, the quietest stretch. Every figure is
 * the server's (`retro.py`). */
import { CalendarDays, Coffee, Globe2, Plane, ShoppingBag, Sparkles, Store, TrendingDown, TrendingUp, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { PageHeader } from "@/components/PageState";
import { Callout, Card, Segmented, Skeleton, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { chf, frDate, plural, signedChf } from "@/lib/format";
import { useView } from "@/lib/url";

interface Retro {
  empty?: boolean; reason?: string;
  years: { year: number; start: string; end: string; months: number; whole: boolean }[];
  chosen: { year: number; start: string; end: string; months: number; whole: boolean };
  year: number; spent: number; earned: number; kept: number; saved_in: number; rate: number | null;
  before: { spent: number; change: number | null } | null; count: number;
  dear: { month: string; amount: number; why: { category: string; amount: number; ordinary: number } | null } | null;
  cheap: { month: string; amount: number } | null;
  months: { month: string; amount: number }[];
  rise: { category: string; amount: number; slot: number | null } | null;
  fall: { category: string; amount: number; slot: number | null } | null;
  categories: { category: string; amount: number; share: number; slot: number | null }[];
  regular: { label: string; visits: number } | null;
  biggest_shop: { label: string; amount: number } | null;
  single: { label: string; amount: number; date: string; category: string } | null;
  new_shops: number | null;
  countries: { country: string; days: number }[];
  stays: { name: string; start: string; end: string; net: number }[];
  weekday: string | null;
  quiet: { days: number; start: string; end: string } | null;
}

const slotColor = (slot: number | null | undefined) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");
const pctText = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(0)} %`;

export default function RetroPage() {
  const { params, href } = useView();
  const q = new URLSearchParams();
  const y = params.get("year");
  if (y) q.set("year", y);
  const { data, isPending, isPlaceholderData, error } = useApi<Retro>("/api/bilan", q);
  if (error) return <Callout tone="bad" title="Le bilan n'a pas pu être chargé">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-48 rounded-card" /></div>;
  if (data.empty) return <Callout title="Pas encore de bilan">{data.reason ?? "Aucun relevé."}</Callout>;
  const c = data.chosen;
  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <PageHeader
        eyebrow="Bilan"
        title={`Ton année ${data.year}`}
        subtitle={c.whole ? `du 1er janvier au 31 décembre · ${plural(data.count, "dépense")}`
          : `${frDate(c.start)} → ${frDate(c.end)}, ce que le relevé en montre · ${plural(data.count, "dépense")}`}
        actions={<Segmented size="sm" label="Année" value={data.year}
                            options={data.years.map((x) => ({ id: x.year, label: x.whole ? String(x.year) : `${x.year}*` }))}
                            hrefFor={(id) => href({ year: String(id) }, { keep: ["year"] })} />}
      />
      <div className="grid gap-4 sm:gap-5 md:grid-cols-2 xl:grid-cols-3">
        <Hero r={data} />
        <MonthsCard r={data} />
        {data.dear && (
          <Fact icon={<Trophy size={18} />} eyebrow="Le mois le plus cher" big={data.dear.month} tone="var(--critical)">
            {chf(data.dear.amount, 0)} CHF
            {data.dear.why && <>, surtout {data.dear.why.category.toLowerCase()} : {chf(data.dear.why.amount, 0)} CHF contre {chf(data.dear.why.ordinary, 0)} CHF un mois ordinaire.</>}
          </Fact>
        )}
        {data.cheap && (
          <Fact icon={<Sparkles size={18} />} eyebrow="Le plus léger" big={data.cheap.month} tone="var(--good)">
            {chf(data.cheap.amount, 0)} CHF dépensés.
          </Fact>
        )}
        <Where r={data} />
        {(data.rise || data.fall) && (
          <Card className="p-5">
            <div className="eyebrow">Par rapport à {data.year - 1}</div>
            <div className="mt-3 space-y-3 text-[14px]">
              {data.rise && <Move icon={<TrendingUp size={17} />} tone="text-critical" label={data.rise.category} amount={data.rise.amount} />}
              {data.fall && <Move icon={<TrendingDown size={17} />} tone="text-good" label={data.fall.category} amount={data.fall.amount} />}
            </div>
            <p className="mt-3 text-[12px] text-muted">Mois pour mois, quand l'une des deux années est incomplète.</p>
          </Card>
        )}
        {data.regular && (
          <Fact icon={<Coffee size={18} />} eyebrow="Ton habitude" big={data.regular.label}>
            {plural(data.regular.visits, "passage")} dans l'année{data.weekday ? `, et c'est le ${data.weekday} que tu sors le plus la carte` : ""}.
          </Fact>
        )}
        {data.biggest_shop && (
          <Fact icon={<Store size={18} />} eyebrow="Là où tu as laissé le plus" big={data.biggest_shop.label}>
            {chf(data.biggest_shop.amount, 0)} CHF sur l'année, factures mises à part.
          </Fact>
        )}
        {data.single && (
          <Fact icon={<ShoppingBag size={18} />} eyebrow="La plus grosse dépense" big={`${chf(data.single.amount, 0)} CHF`}>
            {data.single.label}, le {frDate(data.single.date)} ({data.single.category.toLowerCase()}).
          </Fact>
        )}
        {data.new_shops != null && (
          <Fact icon={<Sparkles size={18} />} eyebrow="Nouveaux noms" big={String(data.new_shops)}>
            bénéficiaires payés pour la première fois cette année.
          </Fact>
        )}
        {data.countries.length > 0 && <Abroad r={data} />}
        {data.quiet && (
          <Fact icon={<CalendarDays size={18} />} eyebrow="La plus longue pause" big={plural(data.quiet.days, "jour")}>
            sans un paiement par carte, du {frDate(data.quiet.start)} au {frDate(data.quiet.end)}.
          </Fact>
        )}
      </div>
    </div>
  );
}

function Hero({ r }: { r: Retro }) {
  return (
    <Card className="relative overflow-hidden p-5 md:col-span-2 xl:col-span-1 xl:row-span-2">
      <div className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-[color-mix(in_srgb,var(--s0)_18%,transparent)] blur-2xl" />
      <div className="eyebrow">L'année en trois chiffres</div>
      <dl className="mt-3 space-y-4">
        <div>
          <dt className="text-[13px] text-muted">Encaissé</dt>
          <dd className="num text-[30px] font-semibold tracking-[-0.03em]">{chf(r.earned, 0)}</dd>
        </div>
        <div>
          <dt className="text-[13px] text-muted">Dépensé</dt>
          <dd className="num text-[30px] font-semibold tracking-[-0.03em]">{chf(r.spent, 0)}</dd>
          {r.before?.change != null && (
            <dd className={cx("text-[12.5px]", r.before.change > 0 ? "text-critical" : "text-good")}>{pctText(r.before.change)} par rapport à {r.year - 1}, mois pour mois</dd>
          )}
        </div>
        <div>
          <dt className="text-[13px] text-muted">Gardé</dt>
          <dd className={cx("num text-[30px] font-semibold tracking-[-0.03em]", r.kept >= 0 ? "text-good" : "text-critical")}>{signedChf(r.kept, 0)}</dd>
          {r.rate != null && <dd className="text-[12.5px] text-muted">{r.rate.toFixed(0)} % de ce qui est entré{r.saved_in > 0 ? `, dont ${chf(r.saved_in, 0)} CHF placés` : ""}</dd>}
        </div>
      </dl>
    </Card>
  );
}

function MonthsCard({ r }: { r: Retro }) {
  const max = Math.max(...r.months.map((m) => m.amount), 1);
  return (
    <Card className="p-5">
      <div className="eyebrow">Mois par mois</div>
      <div className="mt-4 flex h-28 items-end gap-1" role="img" aria-label="Dépense de chaque mois">
        {r.months.map((m) => (
          <div key={m.month} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${m.month} : ${chf(m.amount, 0)} CHF`}>
            <div className={cx("w-full rounded-t-md",
              m.month === r.dear?.month ? "bg-critical" : m.month === r.cheap?.month ? "bg-good" : "bg-[var(--s0)] opacity-60")}
                 style={{ height: `${Math.max((m.amount / max) * 85, 3)}%` }} />
            <span className="text-[10px] text-muted">{m.month.slice(0, 1).toUpperCase()}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Where({ r }: { r: Retro }) {
  return (
    <Card className="p-5">
      <div className="eyebrow">Où est parti l'argent</div>
      <div className="mt-3 flex h-3 w-full gap-[2px] overflow-hidden rounded-full">
        {r.categories.map((c) => <span key={c.category} style={{ width: `${c.share}%`, background: slotColor(c.slot) }} />)}
      </div>
      <ul className="mt-3 space-y-1 text-[13px]">
        {r.categories.map((c) => (
          <li key={c.category} className="flex items-center gap-2">
            <i className="size-2.5 shrink-0 rounded-full" style={{ background: slotColor(c.slot) }} />
            <span className="min-w-0 flex-1 truncate">{c.category}</span>
            <span className="num text-muted">{c.share.toFixed(0)} %</span>
            <span className="num w-20 text-right">{chf(c.amount, 0)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Move({ icon, tone, label, amount }: { icon: ReactNode; tone: string; label: string; amount: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className={cx("grid size-9 shrink-0 place-items-center rounded-xl bg-surface-2", tone)}>{icon}</span>
      <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
      <span className={cx("num font-semibold", tone)}>{signedChf(amount, 0)}</span>
    </div>
  );
}

function Abroad({ r }: { r: Retro }) {
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-ink-2"><Globe2 size={18} /><span className="eyebrow">Ailleurs</span></div>
      <div className="mt-2 text-[22px] font-semibold tracking-[-0.02em]">{plural(r.countries.length, "pays")}</div>
      <ul className="mt-2 flex flex-wrap gap-1.5 text-[12.5px]">
        {r.countries.map((c) => <li key={c.country} className="rounded-full bg-surface-2 px-2.5 py-0.5">{c.country} · {plural(c.days, "jour")}</li>)}
      </ul>
      {r.stays.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px]">
          {r.stays.map((s) => (
            <li key={s.name} className="flex items-center gap-2">
              <Plane size={14} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate">{s.name}</span>
              <span className="num text-muted">{chf(s.net, 0)} CHF</span>
            </li>
          ))}
        </ul>
      )}
      <Link to="/projets" className="mt-3 inline-block text-[12.5px] font-medium text-accent no-underline hover:underline">Les voyages en projets</Link>
    </Card>
  );
}

function Fact({ icon, eyebrow, big, children, tone }: { icon: ReactNode; eyebrow: string; big: string; children: ReactNode; tone?: string }) {
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-ink-2" style={tone ? { color: tone } : undefined}>{icon}<span className="eyebrow" style={tone ? { color: tone } : undefined}>{eyebrow}</span></div>
      <div className="mt-2 line-clamp-2 text-[22px] font-semibold leading-tight tracking-[-0.02em] first-letter:uppercase">{big}</div>
      <p className="mt-1 text-[13px] leading-snug text-ink-2">{children}</p>
    </Card>
  );
}
