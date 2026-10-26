/** What comes next: the commitments the ledger already pays, when each falls
 * due, what they weigh a year and how their price moved, the dates by which
 * they can still be changed, and the health franchise replayed on the care
 * of each year. Every figure is the server's (`api/upcoming`). */
import { AlarmClock, ArrowUpRight, ExternalLink, HeartPulse } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Lines } from "@/charts/Lines";
import { Field, Input } from "@/components/Form";
import { PageHeader } from "@/components/PageState";
import { Spark } from "@/components/Spark";
import { Callout, Card, Chip, Dot, Note, Panel, Segmented, Skeleton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, day, frDate, frDay, MONTHS, pct, plural, signedChf } from "@/lib/format";
import { useView } from "@/lib/url";
import type { Commitment, Deadline, Due, Replay, Upcoming } from "./upcoming/types";
import { Weekly } from "./upcoming/Weekly";

const slotColor = (slot: number | null | undefined) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");
const WEEKDAYS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];

export default function UpcomingPage() {
  const { params } = useView();
  const q = new URLSearchParams();
  const costs = params.get("costs");
  if (costs) q.set("costs", costs);
  const { data, isPending, isPlaceholderData, error } = useApi<Upcoming>("/api/a-venir", q);
  if (error) return <Callout tone="bad" title="La page n'a pas pu être chargée">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-28 rounded-card" /><Skeleton className="h-72 rounded-card" /></div>;
  if (data.empty) return <Callout title="Aucun relevé" />;

  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <PageHeader
        title="À venir"
        subtitle={<>ce que tes engagements vont prélever, lu dans tes paiements · relevé jusqu'au {frDate(data.statement_end)}</>}
      />
      <div className="space-y-4 sm:space-y-5">
        {data.stale > 7 && (
          <Callout tone="warn" title={`Le relevé s'arrête il y a ${data.stale} jours`}
                   action={<Link to="/importer" className="text-[13px] font-medium text-accent">Importer</Link>}>
            Les échéances entre le {frDate(data.statement_end)} et aujourd'hui sont marquées « probablement passée » :
            elles sont sans doute payées, le relevé ne le montre pas encore.
          </Callout>
        )}
        <Headline data={data} />
        {data.deadlines.length > 0 && <Deadlines rows={data.deadlines} />}
        <Calendar data={data} />
        <Commitments data={data} />
        <Franchise data={data} />
        <Weekly />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- headline */

function Headline({ data }: { data: Upcoming }) {
  const [h, setH] = useState(30);
  const t = data.ahead.totals.find((x) => x.days === h) ?? data.ahead.totals[0];
  const s = data.summary;
  const tiles = [
    { label: `D'ici le ${frDay(t.until, false)}`, value: chf(t.out, 0), sub: plural(t.count, "échéance"), tone: "" },
    { label: "Revenus attendus", value: chf(t.in, 0), sub: t.in ? `reste ${signedChf(t.in - t.out, 0)} après les échéances` : "aucun revenu régulier lu", tone: "" },
    { label: "Tes engagements", value: chf(s.yearly, 0), sub: `par an · ${chf(s.monthly, 0)} par mois`, tone: "" },
    { label: "Hausses de prix", value: s.rises ? signedChf(s.rises_yearly, 0) : "aucune", sub: s.rises ? `par an, sur ${plural(s.rises, "engagement")}` : "sur l'année écoulée", tone: s.rises ? "text-critical" : "text-good" },
  ];
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="eyebrow">Les {h} prochains jours</span>
        <Segmented size="sm" label="Horizon" value={h} onChange={setH}
                   options={data.ahead.totals.map((x) => ({ id: x.days, label: `${x.days} j` }))} />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map((x) => (
          <div key={x.label} className="min-w-0">
            <div className="eyebrow">{x.label}</div>
            <div className={cx("num mt-1 text-[22px] font-semibold tracking-[-0.02em]", x.tone)}>{x.value}</div>
            <div className="truncate text-[12px] text-muted">{x.sub}</div>
          </div>
        ))}
      </div>
      <Note>Hors dépenses courantes (courses, sorties) : seulement ce qui revient à date et à montant fixes. La projection complète est dans <Link to="/previsions" className="text-accent">Prévisions</Link>.</Note>
    </Card>
  );
}

/* ------------------------------------------------------------ deadlines */

function Deadlines({ rows }: { rows: Deadline[] }) {
  return (
    <Panel id="p-deadlines" title="À ne pas manquer" hint="les dates jusqu'auxquelles un engagement peut encore changer">
      <ul className="grid gap-3 md:grid-cols-2">
        {rows.map((d) => {
          const soon = d.days <= 45;
          return (
            <li key={d.kind + d.label} className={cx("flex gap-3 rounded-2xl border p-4",
              soon ? "border-[color-mix(in_srgb,var(--warn)_35%,transparent)] bg-[color-mix(in_srgb,var(--warn)_6%,var(--surface))]" : "border-hairline")}>
              <div className="flex w-16 shrink-0 flex-col items-center justify-center rounded-xl bg-surface-2 py-2 text-center">
                <span className="num text-[22px] font-semibold leading-none">{d.days}</span>
                <span className="mt-0.5 text-[11px] text-muted">{d.days > 1 ? "jours" : "jour"}</span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  {d.kind === "lamal" ? <HeartPulse size={15} className="text-critical" /> : <AlarmClock size={15} className="text-ink-2" />}
                  <span className="text-[14px] font-semibold">{d.title}</span>
                  {!d.certain && <Chip>à vérifier</Chip>}
                </div>
                <div className="mt-0.5 text-[12.5px] text-muted">avant le {frDate(d.by)} · {d.label} · {chf(d.monthly, 0)} CHF par mois</div>
                {d.price && d.price.delta > 0 && (
                  <div className="mt-1.5 inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--critical)_10%,transparent)] px-2 py-0.5 text-[12px] font-medium text-critical">
                    <ArrowUpRight size={13} />+{pct(d.price.pct)} depuis le {frDate(d.price.since)} · {signedChf(d.price.yearly_delta, 0)} par an
                  </div>
                )}
                <p className="mt-1.5 text-[12.5px] leading-snug text-ink-2">{d.detail}</p>
                {d.kind === "lamal" && (
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] font-medium">
                    <a href="https://www.priminfo.admin.ch/fr/praemien" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent">
                      Comparer les primes <ExternalLink size={12} />
                    </a>
                    <a href="#p-franchise" className="text-accent">Quelle franchise ?</a>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------- calendar */

function monthOf(iso: string) {
  const d = day(iso);
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function Calendar({ data }: { data: Upcoming }) {
  const [all, setAll] = useState(false);
  const [past, setPast] = useState(false);
  const rows = data.ahead.rows;
  if (!rows.length) return null;
  const until = data.ahead.totals[0].until;
  const pending = rows.filter((r) => r.pending);
  const coming = rows.filter((r) => !r.pending);
  const shown = [...(past ? pending : []), ...(all ? coming : coming.filter((r) => r.day <= until))];
  const groups: { month: string; rows: Due[] }[] = [];
  for (const r of shown) {
    const m = monthOf(r.day);
    if (groups.at(-1)?.month !== m) groups.push({ month: m, rows: [] });
    groups.at(-1)!.rows.push(r);
  }
  const hidden = coming.length - shown.filter((r) => !r.pending).length;
  return (
    <Panel id="p-calendar" title="Les prochaines échéances" hint="chaque engagement à sa date habituelle, et le salaire qui les couvre">
      {pending.length > 0 && (
        <button type="button" onClick={() => setPast(!past)} aria-expanded={past}
                className="mb-3 w-full rounded-xl border border-dashed border-hairline-2 px-3 py-2 text-left text-[12.5px] text-muted hover:text-ink">
          {past ? "Masquer" : "Voir"} {plural(pending.length, "échéance")} entre la fin du relevé et aujourd'hui
          ({chf(data.ahead.pending.out, 0)} CHF), probablement déjà passée{pending.length > 1 ? "s" : ""}
        </button>
      )}
      <div className="space-y-4">
        {groups.map((g) => (
          <div key={g.month}>
            <div className="eyebrow mb-1.5 capitalize">{g.month}</div>
            <ul className="divide-y divide-hairline rounded-2xl border border-hairline">
              {g.rows.map((r, i) => {
                const d = day(r.day);
                return (
                  <li key={r.day + r.label + i} className={cx("flex items-center gap-3 px-3 py-2.5", r.pending && "opacity-55")}>
                    <div className="w-11 shrink-0 text-center leading-tight">
                      <div className="num text-[17px] font-semibold">{d.getDate()}</div>
                      <div className="text-[11px] text-muted">{WEEKDAYS[d.getDay()]}</div>
                    </div>
                    <Dot color={r.out ? slotColor(r.slot) : "var(--good)"} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[14px] font-medium">{r.label}</div>
                      <div className="truncate text-[12px] text-muted">
                        {r.pending ? "probablement passée, pas encore dans le relevé" : `${r.out ? r.category : "revenu"} · ${r.cadence}`}
                      </div>
                    </div>
                    <div className={cx("num shrink-0 text-right text-[14px] font-semibold", !r.out && "text-good")}>
                      {r.out ? "" : "+"}{r.variable ? "≈ " : ""}{chf(r.amount, 0)}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      {hidden > 0 || all ? (
        <button type="button" onClick={() => setAll(!all)} className="mt-3 text-[13px] font-medium text-accent hover:underline">
          {all ? "Les 30 prochains jours seulement" : `Jusqu'à 90 jours (${hidden} de plus)`}
        </button>
      ) : null}
      <Note>« ≈ » : un montant qui varie d'une fois à l'autre (l'électricité), ici le plus récent. Une date suit le jour du mois habituel du paiement.</Note>
    </Panel>
  );
}

/* ---------------------------------------------------------- commitments */

function Commitments({ data }: { data: Upcoming }) {
  const { pageHref } = useView();
  const [order, setOrder] = useState<"yearly" | "next" | "rise">("yearly");
  const rows = [...data.commitments].sort((a, b) =>
    order === "next" ? a.next.localeCompare(b.next)
      : order === "rise" ? (b.price?.yearly_delta ?? -1e9) - (a.price?.yearly_delta ?? -1e9)
        : b.yearly - a.yearly);
  const max = Math.max(...data.commitments.map((c) => c.yearly), 1);
  const link = (c: Commitment) => {
    const base = pageHref("/transactions", { from: c.first, to: data.statement_end, preset: null, grain: null });
    return `${base}${base.includes("?") ? "&" : "?"}q=${encodeURIComponent(c.label)}`;
  };
  return (
    <Panel id="p-commitments" title="Tes engagements" hint={`${plural(data.summary.count, "paiement")} qui revien${data.summary.count > 1 ? "nent" : "t"} seul${data.summary.count > 1 ? "s" : ""}, ce qu'ils pèsent par an`}
           actions={<Segmented size="sm" label="Ordre" value={order} onChange={setOrder}
                               options={[{ id: "yearly", label: "Par an" }, { id: "next", label: "Prochain" }, { id: "rise", label: "Hausses" }]} />}>
      <ul className="divide-y divide-hairline">
        {rows.map((c) => (
          <li key={c.label}>
            <Link to={link(c)} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2.5 no-underline hover:bg-surface-2/60 sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_5rem_auto] sm:rounded-lg sm:px-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Dot color={slotColor(c.slot)} />
                  <span className="truncate text-[14px] font-medium">{c.label}</span>
                </div>
                <div className="truncate pl-4 text-[12px] text-muted">{c.subcategory || c.category} · {c.cadence} · prochain le {frDay(c.next, false)}</div>
              </div>
              <div className="hidden min-w-0 sm:block">
                <div className="h-2 rounded-full bg-surface-2"><div className="h-full rounded-full" style={{ width: `${(c.yearly / max) * 100}%`, background: slotColor(c.slot) }} /></div>
              </div>
              <div className="hidden w-20 sm:block">{new Set(c.spark).size > 1 && <Spark values={c.spark} color={slotColor(c.slot)} className="h-6 w-20" />}</div>
              <div className="text-right">
                <div className="num text-[14px] font-semibold">{chf(c.yearly, 0)}<span className="ml-1 text-[11.5px] font-normal text-muted">/an</span></div>
                <div className="num text-[12px] text-muted">
                  {c.price
                    ? <span className={c.price.delta > 0 ? "text-critical" : "text-good"}>{c.price.delta > 0 ? "+" : ""}{pct(c.price.pct)} · {chf(c.price.before, 2)} → {chf(c.price.now, 2)}</span>
                    : <>{c.variable ? "≈ " : ""}{chf(c.amount, 2)} {c.cadence}</>}
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      <Note>Un engagement est un bénéficiaire payé à rythme et à montant réguliers, encore actif à la fin du relevé. Un paiement par carte n'en est un que s'il se renouvelle seul (un abonnement). Une hausse se mesure contre le paiement d'il y a un an.</Note>
    </Panel>
  );
}

/* ------------------------------------------------------------ franchise */

const FRANCHISE_SLOTS = [0, 1, 2, 3, 4, 5];

function Franchise({ data }: { data: Upcoming }) {
  const h = data.health;
  const { href, go } = useView();
  const [typed, setTyped] = useState<string | null>(null);
  if (!h.premium || !h.replay) {
    return (
      <Panel id="p-franchise" title="Ta franchise LAMal, rejouée" hint="quelle franchise t'aurait coûté le moins">
        <Note className="mt-0">Aucune prime mensuelle d'assurance maladie n'est lue dans le relevé : le calcul a besoin de la prime que tu paies.</Note>
      </Panel>
    );
  }
  const r = h.replay;
  const declare = async (f: number) => {
    await send("/api/health", { franchise: f });
    toast(`Franchise ${chf(f, 0)} retenue`);
  };
  const apply = () => {
    const v = (typed ?? "").replace(/['’\s]/g, "");
    if (v && !Number.isNaN(Number(v))) go({ costs: v }, { keep: ["costs"], replace: true });
    setTyped(null);
  };
  const current = r.rows.find((x) => x.franchise === r.franchise)!;
  const best = r.rows.find((x) => x.franchise === r.best)!;
  const idx = Math.min(Math.round(r.costs / (r.axis[1] - r.axis[0])), r.axis.length - 1);
  return (
    <Panel id="p-franchise" title="Ta franchise LAMal, rejouée" hint={`prime ${h.premium.label} : ${chf(r.premium, 2)} CHF par mois · pour quelle franchise ?`}>
      {!h.settings.declared && (
        <Callout className="mb-4" title="Quelle est ta franchise ?">
          Indique-la : le calcul part de la prime que tu paies pour elle, et en déduit tes frais de santé.
        </Callout>
      )}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div className="min-w-0 space-y-4">
          <div>
            <div className="mb-1.5 text-[12.5px] font-medium text-ink-2">Ta franchise aujourd'hui</div>
            <Segmented size="sm" label="Ta franchise" value={r.franchise} onChange={declare}
                       options={h.franchises.map((f) => ({ id: f, label: chf(f, 0) }))} />
          </div>
          <div>
            <Field label="Frais de santé d'une année (factures totales)">
              {(id) => (
                <Input id={id} inputMode="decimal" className="max-w-[10rem]" value={typed ?? chf(r.costs, 0)}
                       onChange={(e) => setTyped(e.target.value)} onBlur={apply}
                       onKeyDown={(e) => { if (e.key === "Enter") apply(); }} />
              )}
            </Field>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {h.years.map((y) => (
                <Link key={y.year} to={href({ costs: String(Math.round(y.costs)) }, { keep: ["costs"] })} replace
                      className={cx("rounded-full border px-2.5 py-0.5 text-[12px] no-underline",
                        Math.round(y.costs) === Math.round(r.costs) ? "border-ink bg-ink text-page" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
                  {y.year}{y.whole ? "" : "*"} · {y.exact ? "" : "≥ "}{chf(y.costs, 0)}
                </Link>
              ))}
            </div>
          </div>
          <div className={cx("rounded-2xl p-4", r.best === r.franchise ? "bg-[color-mix(in_srgb,var(--good)_9%,var(--surface))]" : "bg-[color-mix(in_srgb,var(--s0)_8%,var(--surface))]")}>
            {r.best === r.franchise ? (
              <p className="text-[14px]"><b>Ta franchise est la bonne</b> pour {chf(r.costs, 0)} CHF de soins : {chf(current.total, 0)} CHF dans l'année, primes comprises.</p>
            ) : (
              <p className="text-[14px]">Avec {chf(r.costs, 0)} CHF de soins, la franchise <b>{chf(r.best, 0)}</b> t'aurait coûté <b className="text-good">{chf(r.saving, 0)} CHF de moins</b> : {chf(best.total, 0)} au lieu de {chf(current.total, 0)}.</p>
            )}
            {r.crossing != null && (
              <p className="mt-1.5 text-[12.5px] text-ink-2">En dessous d'environ <b>{chf(r.crossing, 0)} CHF</b> de soins par an, la franchise la plus haute coûte moins que la plus basse.</p>
            )}
          </div>
        </div>
        <div className="min-w-0">
          <Lines xs={r.axis} height={220}
                 series={r.curves.map((c, i) => ({ key: String(c.franchise), name: `Franchise ${chf(c.franchise, 0)}`,
                   color: `var(--s${FRANCHISE_SLOTS[i]})`, values: c.values,
                   width: c.franchise === r.franchise ? 2.75 : 1.5, faint: c.franchise !== r.franchise && c.franchise !== r.best }))}
                 markers={[{ index: idx, series: String(r.best), label: "toi" }]}
                 tipFormat={(v) => `${chf(v, 0)} CHF`}
                 xLabel={(i) => `${chf(r.axis[i], 0)} CHF de soins`}
                 xTicks={(w) => r.axis.map((x, i) => ({ index: i, label: chf(x, 0) })).filter((_, i) => i % (w < 420 ? 20 : 10) === 0)}
                 zero={false}
                 ariaLabel="Coût annuel de chaque franchise selon les frais de santé" />
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-ink-2">
            {r.curves.map((c, i) => (
              <span key={c.franchise} className="inline-flex items-center gap-1.5"><Dot color={`var(--s${FRANCHISE_SLOTS[i]})`} />{chf(c.franchise, 0)}</span>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[520px] text-[13px]">
          <thead className="text-left text-[12px] text-muted">
            <tr><th className="py-1.5 font-medium">Franchise</th><th className="text-right font-medium">Prime / mois</th><th className="text-right font-medium">Primes / an</th><th className="text-right font-medium">À ta charge</th><th className="text-right font-medium">Total</th></tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {r.rows.map((x) => (
              <tr key={x.franchise} className={cx(x.franchise === r.best && "font-semibold")}>
                <td className="py-1.5">{chf(x.franchise, 0)}{x.franchise === r.franchise && <span className="ml-1.5 text-[11px] font-normal text-muted">la tienne</span>}{x.franchise === r.best && <span className="ml-1.5 text-[11px] text-good">la moins chère</span>}</td>
                <td className="num text-right">{chf(x.premium, 2)}</td>
                <td className="num text-right">{chf(x.premiums, 0)}</td>
                <td className="num text-right">{chf(x.left, 0)}</td>
                <td className="num text-right">{chf(x.total, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {r.years.length > 0 && <Years r={r} />}
      <Note>
        À ta charge : la franchise, puis {r.rules.quote_part} % du reste jusqu'à {chf(r.rules.cap, 0)} CHF par an. Les autres primes supposent
        le rabais le plus grand que la loi permet ({r.rules.discount} % du risque supplémentaire) : beaucoup de caisses l'accordent, pas toutes.
        Les primes exactes sont sur <a href="https://www.priminfo.admin.ch/fr/praemien" target="_blank" rel="noreferrer" className="text-accent">priminfo.admin.ch</a>.
        Pour le 1er janvier : une franchise plus basse se demande par écrit avant le 30 novembre, une plus haute jusqu'au 31 décembre.
      </Note>
    </Panel>
  );
}

function Years({ r }: { r: Replay }) {
  return (
    <div className="mt-5">
      <h3 className="mb-1 text-[14px] font-semibold">Tes années, rejouées</h3>
      <p className="mb-2 text-[12.5px] text-muted">Ta part de chaque année (payé aux soignants et facturé par la caisse, moins ses remboursements), relue à travers ta franchise pour retrouver les frais totaux.</p>
      <ul className="divide-y divide-hairline rounded-2xl border border-hairline">
        {r.years.map((y) => (
          <li key={y.year} className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 px-3 py-2.5 text-[13px] sm:grid-cols-[3.5rem_minmax(0,1fr)_auto]">
            <span className="num font-semibold">{y.year}{!y.whole && "*"}</span>
            <span className="min-w-0 truncate text-ink-2">ta part {chf(y.share, 0)} · frais {y.exact ? "≈" : "≥"} {chf(y.costs, 0)} CHF</span>
            <span className="col-start-2 sm:col-start-auto sm:text-right">
              {y.best === r.franchise
                ? <span className="text-good">ta franchise était la bonne</span>
                : <>franchise <b>{chf(y.best ?? 0, 0)}</b> <span className="text-good">−{chf(y.saving ?? 0, 0)}</span></>}
            </span>
          </li>
        ))}
      </ul>
      <Note>* année incomplète dans le relevé. « ≥ » : ta part a atteint le plafond, les frais réels peuvent être plus hauts. Sous le tiers payant, la caisse paie la pharmacie sans passer par ton compte : ce qu'elle te refacture ensuite est compté.</Note>
    </div>
  );
}
