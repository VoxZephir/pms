/** The analytical panels, each scoped to the window. A panel that cannot
 * say anything on this window is absent (the API's `panels` gates). */
import { Pencil, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { CalendarHeat } from "@/charts/Calendar";
import { Columns } from "@/charts/Columns";
import { Lines, monthTicks, spreadTicks } from "@/charts/Lines";
import { MonthAssist } from "@/components/Assist";
import { Sheet } from "@/components/Sheet";
import { Table } from "@/components/Table";
import { Button, Card, Chip, Dot, Note, Panel, Reveal, Segmented, Track, cx } from "@/components/ui";
import { send } from "@/lib/api";
import { MONTHS_SHORT, chf, compact, day, frDate, frDay, pct, plural } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import { useView } from "@/lib/url";

type P = { data: Dashboard };

/* ------------------------------------------------------------- review */

export function Review({ data }: P) {
  const r = data.review!;
  const { pageHref } = useView();
  const win = { from: r.first, to: r.last };
  const lists: { title: string; empty: string; items: { key: string; label: string; href: string; value: React.ReactNode }[] }[] = [
    {
      title: "Prix qui ont changé",
      empty: "Aucun : les engagements à prix fixe ont gardé leur prix.",
      items: r.prices.map((p) => ({
        key: p.label, label: p.label, href: pageHref("/transactions", { ...win, q: p.label }),
        value: <span className="num">{chf(p.before)} → {chf(p.now)} <Chip tone={p.delta > 0 ? "bad" : "good"}>{p.delta > 0 ? "+" : ""}{p.pct.toFixed(1)} %</Chip></span>,
      })),
    },
    {
      title: "Nouveaux bénéficiaires",
      empty: "Aucun nouveau bénéficiaire, aucun gros achat chez un nouveau commerçant.",
      items: r.new_payees.map((p) => ({
        key: p.label, label: p.label, href: pageHref("/transactions", { ...win, q: p.label }),
        value: <span className="num">{chf(p.amount, 0)} CHF</span>,
      })),
    },
    {
      title: "Débits peut-être doublés",
      empty: "Aucun montant identique chez le même bénéficiaire à moins de trois jours.",
      items: r.duplicates.map((d) => ({
        key: d.label + d.dates.join(), label: d.label, href: pageHref("/transactions", { ...win, q: d.label }),
        value: <span className="num">2 × {chf(d.amount)} · {frDay(d.dates[0], false)}{d.dates[1] !== d.dates[0] ? ` et ${frDay(d.dates[1], false)}` : ""}</span>,
      })),
    },
    {
      title: "Au-dessus de l'habitude",
      empty: "Chaque catégorie est restée dans sa fourchette habituelle.",
      items: r.categories.map((c) => ({
        key: c.category, label: c.category, href: pageHref("/transactions", { ...win, category: c.category }),
        value: <span className="num">{chf(c.amount, 0)} · {c.seasonal ? `l'an passé ${chf(c.habit, 0)}` : c.habit < 1 ? "d'habitude rien" : `d'habitude ${chf(c.habit, 0)}`}</span>,
      })),
    },
  ];
  return (
    <Panel id="p-review" title={`Revue du mois · ${r.label}`}
           hint={`${r.partial ? `mois en cours, au ${frDate(r.last)} · ` : ""}comparé aux ${r.history_months} mois entiers qui précèdent`}>
      <p className="text-[15px] text-ink-2">
        <b className="num text-ink">{chf(r.spent, 0)} CHF</b> dépensés{r.partial ? " à ce jour" : ""}, pour une médiane de{" "}
        <span className="num">{chf(r.median, 0)} CHF</span> par mois entier
        {r.delta_pct != null && !r.partial && <> ({r.delta_pct >= 0 ? "+" : ""}{Math.round(r.delta_pct)} %)</>}.
      </p>
      <MonthAssist first={r.first} last={r.last} />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {lists.map((l) => (
          <div key={l.title} className="rounded-2xl bg-surface-2/50 p-3.5">
            <h3 className="mb-2 text-[13px] font-semibold">{l.title}</h3>
            {l.items.length ? (
              <ul className="space-y-1.5 text-[13px]">
                {l.items.map((i) => (
                  <li key={i.key} className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <Link to={i.href} className="min-w-0 truncate font-medium underline-offset-2 hover:underline">{i.label}</Link>
                    <span className="text-ink-2">{i.value}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[12.5px] text-muted">{l.empty}</p>}
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* --------------------------------------------------------------- shares */

export function Shares({ data }: P) {
  const { href } = useView();
  const s = data.shares;
  const names = s.names.filter((n) => s.rows.some((r) => r.smooth[n] != null || r.raw[n] != null));
  const xs = s.rows.map((_, i) => i);
  const series = names.flatMap((n) => [
    ...(s.smooth > 1 ? [{ key: `${n}-raw`, name: `${n} brut`, color: data.bucket_fill[n], values: s.rows.map((r) => r.raw[n]), faint: true, silent: true }] : []),
    { key: n, name: n, color: data.bucket_fill[n], values: s.rows.map((r) => r.smooth[n]) },
  ]);
  const clamp: [number, number] = s.base === "spending" ? [0, 100] : [-100, 200];
  return (
    <Panel id="p-shares" foldable defaultOpen={false}
           title="Évolution des parts besoins, envies, épargne"
           hint={`mois par mois${s.smooth > 1 ? `, sur ${s.smooth} mois glissants` : ""}`}>
      <div className="mb-3 flex flex-wrap gap-3">
        <Segmented size="sm" label="Base du pourcentage" value={s.base}
                   options={s.bases.map((b) => ({ id: b.id, label: `En part des ${b.label.toLowerCase()}` }))}
                   hrefFor={(id) => href({ shares: id })} />
        <Segmented size="sm" label="Lissage" value={s.smooth}
                   options={s.smoothings.map((m) => ({ id: m, label: m === 1 ? "Brut" : `${m} mois` }))}
                   hrefFor={(id) => href({ smooth: id === 1 ? null : id, shares: s.base })} />
      </div>
      <Lines xs={xs} series={series} height={260} zero={false} clamp={clamp}
             format={(v) => `${Math.round(v)} %`} tipFormat={(v) => pct(v)}
             xLabel={(i) => s.rows[i].label}
             xTicks={(w) => spreadTicks(xs.length, w, (i) => s.rows[i].label, 64)}
             refs={s.base === "income" ? Object.entries(s.targets).filter(([n]) => names.includes(n))
               .map(([n, v]) => ({ value: v, color: data.bucket_fill[n], label: `${n} ${v} %` })) : []}
             endLabels ariaLabel="Part de chaque bloc, mois par mois" />
      <Note>
        {s.base === "income"
          ? "En part des revenus du mois : les quatre blocs font 100 %, et Save est ce qui n'a pas été dépensé — négatif un mois qui a dépensé plus qu'il n'a encaissé."
          : "En part des dépenses : besoins, envies et non classé font 100 % de ce qui a été consommé."}
        {s.smooth > 1 && ` Lissé sur ${s.smooth} mois glissants : la somme de chaque bloc divisée par la somme de la base. Les lignes pâles sont les mois bruts.`}
        {" "}Seuls les mois entiers comptent.
      </Note>
    </Panel>
  );
}

/* ---------------------------------------------------------- merchants */

export function Merchants({ data }: P) {
  const { pageHref } = useView();
  const top = data.top_merchants[0]?.amount || 1;
  if (!data.top_merchants.length) return null;
  return (
    <Panel title="Principaux bénéficiaires" hint="sur la période">
      <ul className="-mx-2 grid gap-x-6 sm:grid-cols-2">
        {data.top_merchants.map((m) => (
          <li key={m.name}>
            <Link to={pageHref("/transactions", { from: data.period.start, to: data.period.end, q: m.name })}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-xl px-2 py-2 no-underline transition hover:bg-surface-2"
                  title={`${m.count} paiements · moyenne ${chf(m.average)} · médiane ${chf(m.median)} · ${m.category}${m.mixed ? ` (${Math.round(m.category_share)} %)` : ""}`}>
              <span className="truncate text-[14px] font-medium">{m.name}</span>
              <span className="num text-right text-[13.5px] font-semibold">{chf(m.amount, 0)} <span className="font-normal text-muted">· {m.count}×</span></span>
              <Track value={(m.amount / top) * 100} color="var(--s0)" className="col-span-2 h-1.5" />
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------- balance */

export function Balance({ data }: P) {
  const pts = data.balance;
  const step = Math.max(1, Math.floor(pts.length / 600));
  const thin = useMemo(() => pts.filter((_, i) => i % step === 0 || i === pts.length - 1), [pts, step]);
  if (thin.length < 2) return null;
  const xs = thin.map((p) => day(p[0]).getTime());
  const values = thin.map((p) => p[1]);
  const peak = values.indexOf(Math.max(...values));
  return (
    <Panel id="p-balance" title="Évolution du solde" hint={`${frDate(thin[0][0])} → ${frDate(thin[thin.length - 1][0])}`}>
      <Lines xs={xs} height={220}
             series={[{ key: "bal", name: "Solde", color: "var(--s0)", values, area: true }]}
             xLabel={(i) => frDate(thin[i][0])} tipFormat={(v) => `${chf(v)} CHF`}
             xTicks={(w) => monthTicks(xs, w, 64)}
             markers={[{ index: peak, series: "bal", label: `pic ${chf(values[peak], 0)}` }]}
             ariaLabel="Évolution du solde, tous comptes, en francs" />
      <Note>Solde des comptes en CHF après chaque mouvement, tel qu'imprimé par la banque.</Note>
    </Panel>
  );
}

/* ---------------------------------------------------------- highlights */

export function Highlights({ data }: P) {
  return (
    <section id="p-highlights" className="scroll-mt-24">
      <h2 className="mb-3 px-1 text-[17px] font-semibold tracking-tight">Faits marquants</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.highlights.map((h) => (
          <Card key={h.label} className="p-4">
            <div className="eyebrow">{h.label}</div>
            <div className="mt-1.5 text-[18px] font-semibold tracking-tight">{h.value}</div>
            <div className="mt-0.5 text-[13px] text-muted">{h.detail}</div>
          </Card>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- income */

export function Income({ data }: P) {
  const { pageHref } = useView();
  const inc = data.income!;
  const color = (label: string) => `var(--s${inc.slots[label] ?? inc.slots["Autres"] ?? 7})`;
  const gaps = inc.rows.filter((r) => r.total <= 0).length;
  const columns = inc.rows.map((r) => ({
    key: r.key, label: r.label,
    segments: Object.entries(r.sources).map(([name, v]) => ({ name, value: r.total ? (v / r.total) * 100 : 0, color: color(name) })),
    total: r.total > 0 ? 100 : 0, hollow: r.total <= 0,
  }));
  return (
    <Panel id="p-income" title="D'où vient l'argent"
           hint={`${plural(inc.payers, "payeur")}${gaps ? ` · ${plural(gaps, "période")} sans aucune entrée` : ""}`}>
      <Columns columns={columns} height={170} fixedMax={100} format={(v) => `${Math.round(v)} %`}
               ariaLabel="Sources de revenu dans le temps, une couleur par payeur"
               tipRows={(c) => {
                 const r = inc.rows.find((x) => x.key === c.key)!;
                 if (r.total <= 0) return [{ name: "Aucune entrée", value: "—" }];
                 return Object.entries(r.sources).sort((a, b) => b[1] - a[1])
                   .map(([n, v]) => ({ name: n, value: `${chf(v, 0)} · ${Math.round((v / r.total) * 100)} %`, color: color(n) }));
               }} />
      <div className="mt-4">
        <Table rows={inc.table} rowKey={(r) => r.label}
               cols={[
                 { key: "label", label: "Payeur", sort: (r) => r.label, render: (r) => (
                   <span className="flex items-center gap-2"><Dot color={`var(--s${r.slot})`} />
                     {r.folded ? r.label : <Link to={pageHref("/transactions", { from: data.period.start, to: data.period.end, q: r.label, dir: "in" })} className="underline-offset-2 hover:underline">{r.label}</Link>}
                   </span>) },
                 { key: "first", label: "Du", sort: (r) => r.first, render: (r) => <span className="num">{frDate(r.first)}</span>, wide: true },
                 { key: "last", label: "Au", sort: (r) => r.last, render: (r) => <span className="num">{frDate(r.last)}</span>, wide: true },
                 { key: "count", label: "Versements", numeric: true, sort: (r) => r.count, render: (r) => r.count },
                 { key: "amount", label: "Total", numeric: true, sort: (r) => r.amount, render: (r) => chf(r.amount) },
                 { key: "share", label: "Part", numeric: true, sort: (r) => r.share, render: (r) => pct(r.share) },
               ]} />
      </div>
      <Note>La bande donne la part de chaque payeur dans la période, pas le montant : le combien est le repère vert du graphique des dépenses. Au-delà des plus gros payeurs, le reste est replié sur « Autres ».</Note>
    </Panel>
  );
}

/* -------------------------------------------------------------- missing */

export function Missing({ data }: P) {
  const { pageHref } = useView();
  return (
    <Panel id="p-missing" title="Engagements sans passage récent" hint={`au ${frDate(data.period.end)}, fin de la période affichée`}>
      <Table rows={data.missing} rowKey={(r) => r.label}
             cols={[
               { key: "label", label: "Bénéficiaire", sort: (r) => r.label, render: (r) => (
                 <span className="flex flex-wrap items-center gap-2">
                   <Link to={pageHref("/transactions", { from: data.period.start, to: data.period.end, q: r.label })} className="font-medium underline-offset-2 hover:underline">{r.label}</Link>
                   {r.ended && <Chip title="Silencieux depuis plus de trois fois son intervalle">semble arrêté</Chip>}
                 </span>) },
               { key: "category", label: "Catégorie", sort: (r) => r.category, render: (r) => <Chip>{r.category}</Chip>, wide: true },
               { key: "last", label: "Dernier passage", sort: (r) => r.last, render: (r) => <span className="num">{frDate(r.last)}</span> },
               { key: "expected", label: "Attendu vers", sort: (r) => r.expected, render: (r) => <span className="num">{frDate(r.expected)}</span> },
               { key: "average", label: "Montant habituel", numeric: true, sort: (r) => r.average, render: (r) => <>{chf(r.average)} <span className="text-muted">· tous les {Math.round(r.interval)} j</span></> },
               { key: "late", label: "Retard", numeric: true, sort: (r) => r.gap - r.interval, render: (r) => `${Math.round(r.gap - r.interval)} j` },
             ]} />
      <Note>Le rythme est l'écart médian entre deux passages. Les derniers jours d'un relevé étant toujours incomplets, rien n'est signalé avant une semaine pleine de retard.</Note>
    </Panel>
  );
}

/* ---------------------------------------------------------------- fixed */

export function Fixed({ data }: P) {
  const f = data.fixed!;
  const columns = f.months.map((m) => {
    const [y, mo] = m.month.split("-").map(Number);
    return {
      key: m.month, label: `${MONTHS_SHORT[mo - 1]} ${String(y).slice(2)}`,
      segments: [
        { name: "Socle contraint", value: m.fixed, color: "var(--s0)" },
        { name: "Variable", value: m.variable, color: "var(--s1)" },
      ],
      total: m.fixed + m.variable,
    };
  });
  return (
    <Panel id="p-fixed" title="Socle contraint et dépenses choisies" hint={`socle médian ${chf(f.monthly_floor, 0)} CHF/mois`}>
      <Columns columns={columns} height={260} stackOrder="given"
               reference={f.monthly_floor} referenceLabel={`socle médian ${chf(f.monthly_floor, 0)}`}
               ariaLabel="Dépenses mensuelles, socle contraint et dépenses variables"
               tipFooter={(c) => <div className="flex justify-between"><span>Total</span><b className="num">{chf(c.total, 0)} CHF</b></div>} />
      <div className="mt-3 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><Dot color="var(--s0)" />Socle contraint · {pct(f.fixed_share)}</span>
        <span className="inline-flex items-center gap-1.5"><Dot color="var(--s1)" />Dépenses variables</span>
      </div>
      <Reveal className="mt-3" summary={`Voir les ${f.commitment_count} engagements récurrents`}>
        <Table rows={f.commitments} rowKey={(r) => r.label} dense
               cols={[
                 { key: "label", label: "Bénéficiaire", sort: (r) => r.label, render: (r) => r.label },
                 { key: "category", label: "Catégorie", sort: (r) => r.category, render: (r) => <Chip>{r.category}</Chip>, wide: true },
                 { key: "months", label: "Mois", numeric: true, sort: (r) => r.months ?? 0, render: (r) => r.months || "—" },
                 { key: "average", label: "Moyenne", numeric: true, sort: (r) => r.average ?? 0, render: (r) => (r.average ? chf(r.average) : "—") },
                 { key: "total", label: "Total", numeric: true, sort: (r) => r.total, render: (r) => chf(r.total) },
               ]} />
      </Reveal>
      <Note>Fixe = contractuel (loyer, assurances, téléphonie, redevance) ou revenant sur au moins six mois avec un montant stable. Un supermarché fréquenté chaque semaine revient, mais le montant reste un choix.</Note>
    </Panel>
  );
}

/* -------------------------------------------------------------- monthly */

export function Monthly({ data }: P) {
  const [editing, setEditing] = useState<string | null>(null);
  const rows = data.monthly;
  return (
    <Panel id="p-monthly" title="Dépenses par mois" hint="une barre par mois · budgets mensuels">
      <ul className="space-y-1">
        {rows.map((r) => {
          const peak = Math.max(...r.months.map((m) => m.amount), 1);
          const gauge = r.budget ? (r.median / r.budget) * 100 : null;
          return (
            <li key={r.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 rounded-xl px-2 py-2 -mx-2 hover:bg-surface-2/50 sm:grid-cols-[150px_minmax(0,1fr)_100px_150px]">
              <span className="flex min-w-0 items-center gap-2 text-[13.5px] font-medium">
                <Dot color={`var(--s${r.slot})`} /><span className="truncate">{r.name}</span>
              </span>
              <span className="col-span-2 row-start-2 flex h-9 items-end gap-[2px] sm:col-span-1 sm:row-start-auto" role="img" aria-label={`${r.name} par mois`}>
                {r.months.map((m) => (
                  <i key={m.key} title={`${m.label} : ${chf(m.amount, 0)} CHF`}
                     className="min-w-[2px] flex-1 rounded-t-[3px] transition-[height]"
                     style={{ height: `${Math.max(m.amount ? 6 : 0, (m.amount / peak) * 100)}%`, background: `var(--s${r.slot})`, opacity: m.amount ? 1 : 0 }} />
                ))}
              </span>
              <span className="num text-right text-[13.5px] font-semibold" title={`médiane ${chf(r.median, 0)} CHF/mois`}>
                {chf(r.total, 0)} <span className="text-[11px] font-normal text-muted">CHF</span>
              </span>
              <span className="col-span-2 flex items-center gap-2 sm:col-span-1">
                {r.budget ? (
                  <button type="button" onClick={() => setEditing(r.name)} className="flex min-w-0 flex-1 items-center gap-2 text-left sm:w-44"
                          title="médiane mensuelle de la fenêtre contre le budget déclaré">
                    <Track value={Math.min(gauge ?? 0, 100)} color={gauge! > 100 ? "var(--critical)" : "var(--s2)"} className="w-16 shrink-0" />
                    <span className={cx("num truncate text-[11.5px]", gauge! > 100 ? "text-critical" : "text-muted")}>
                      {chf(r.median, 0)} / {chf(r.budget, 0)}
                    </span>
                  </button>
                ) : (
                  <button type="button" onClick={() => setEditing(r.name)}
                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] text-muted hover:bg-surface-2 hover:text-ink sm:ml-auto">
                    <Pencil size={12} /> budget
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      <Note>Hauteur relative au mois le plus chargé de chaque catégorie. La jauge compare la médiane mensuelle de la fenêtre au budget déclaré (rouge au-delà). Budgets dans <code>data/budgets.json</code>, hors du dépôt.</Note>
      <BudgetSheet name={editing} current={rows.find((r) => r.name === editing)} onClose={() => setEditing(null)} />
    </Panel>
  );
}

function BudgetSheet({ name, current, onClose }: {
  name: string | null; current?: Dashboard["monthly"][number]; onClose: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await send("/api/budgets", { category: name, amount });
      toast.success(`Budget ${name} : ${amount} CHF par mois`);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const remove = async () => {
    await send("/api/budgets", { category: name, action: "delete" });
    toast(`Budget ${name} retiré`);
    onClose();
  };
  return (
    <Sheet open={!!name} onOpenChange={(o) => { if (!o) { onClose(); setAmount(""); setError(""); } }}
           title={`Budget · ${name ?? ""}`}
           description={current ? `médiane ${chf(current.median, 0)} CHF par mois sur la fenêtre` : undefined}>
      <form onSubmit={save} className="space-y-3">
        <label className="block text-[13px] font-medium">
          Budget mensuel, en CHF
          <input type="number" inputMode="decimal" step="0.01" min="0.01" required autoFocus
                 placeholder={current?.budget ? String(current.budget) : String(Math.round(current?.median ?? 0))}
                 value={amount} onChange={(e) => setAmount(e.target.value)}
                 aria-invalid={!!error}
                 className="mt-1.5 h-11 w-full rounded-xl border border-hairline-2 bg-surface px-3 text-[16px]" />
        </label>
        {error && <p className="text-[13px] text-critical" role="alert">{error}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" className="flex-1">Enregistrer</Button>
          {current?.budget && <Button type="button" variant="ghost" onClick={remove}><Trash2 size={15} /> Retirer</Button>}
        </div>
      </form>
    </Sheet>
  );
}

/* ------------------------------------------------------------- calendar */

export function Calendar({ data, onDay }: P & { onDay: (iso: string) => void }) {
  return (
    <Panel id="p-calendar" title="Calendrier des dépenses" hint="une journée ouvre son détail">
      <CalendarHeat daily={data.daily} start={data.period.start} end={data.period.end} onPick={onDay} />
    </Panel>
  );
}

/* ---------------------------------------------------------------- years */

export function Years({ data }: P) {
  const series = data.years.filter((y) => y.points.length);
  const xs = Array.from({ length: 366 }, (_, i) => i + 1);
  const lines = series.map((y, i) => {
    const values: (number | null)[] = xs.map(() => null);
    let pos = 0;
    let current: number | null = null;
    for (const dayN of xs) {
      while (pos < y.points.length && y.points[pos][0] <= dayN) { current = y.points[pos][1]; pos++; }
      values[dayN - 1] = dayN < y.first_day || dayN > y.last_day ? null : current;
    }
    // Eight validated hues; a ninth year goes grey rather than to an unset slot.
    return { key: String(y.year), name: String(y.year), color: i < 8 ? `var(--s${i})` : "var(--unsorted)", values };
  });
  const monthStarts = Array.from({ length: 12 }, (_, m) => ({
    index: Math.round((new Date(2025, m, 1).getTime() - new Date(2025, 0, 1).getTime()) / 86_400_000),
    label: MONTHS_SHORT[m],
  }));
  return (
    <Panel id="p-years" foldable defaultOpen={false} title="Cumul des dépenses, année par année" hint="même jour de l'année, axe unique">
      <Lines xs={xs} series={lines} height={260} endLabels
             xLabel={(i) => { const d = new Date(2025, 0, i + 1); return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`; }}
             xTicks={(w) => monthStarts.filter((_, i) => w > 560 || i % 2 === 0)}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             ariaLabel="Cumul des dépenses par année, au même jour de l'année" />
      <div className="mt-3 flex flex-wrap gap-4 text-[12.5px] text-ink-2">
        {series.map((y, i) => (
          <span key={y.year} className="inline-flex items-center gap-1.5"><Dot color={lines[i].color} />
            {y.year} · {chf(y.total, 0)} CHF{y.first_day > 15 || y.last_day < 350 ? " (année partielle)" : ""}</span>
        ))}
      </div>
    </Panel>
  );
}

/* --------------------------------------------------- weekday and season */

export function Profiles({ data }: P) {
  const wtop = Math.max(...data.weekday.map((d) => d.amount), 1);
  const stop = Math.max(...data.season.map((d) => d.average), 1);
  return (
    <Panel id="p-profiles" foldable defaultOpen={false} title="Par jour de semaine et par mois" hint="où tombent les dépenses">
      <div className="grid gap-6 sm:grid-cols-2">
        <BarList title="Jours de la semaine"
                 rows={data.weekday.map((d) => ({ key: d.day, label: d.day, value: d.amount, pct: (d.amount / wtop) * 100, aside: `${d.count}×` }))} />
        {data.season.length > 0 && (
          <BarList title="Moyenne par mois calendaire"
                   rows={data.season.map((r) => ({ key: String(r.month), label: MONTHS_SHORT[r.month - 1], value: r.average, pct: (r.average / stop) * 100, aside: `${r.years} a` }))} />
        )}
      </div>
    </Panel>
  );
}

function BarList({ title, rows }: { title: string; rows: { key: string; label: string; value: number; pct: number; aside?: string }[] }) {
  return (
    <div>
      <h3 className="mb-2 text-[13px] font-semibold">{title}</h3>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} className="grid grid-cols-[72px_minmax(0,1fr)_auto] items-center gap-3 text-[13px]">
            <span className="truncate capitalize text-ink-2">{r.label}</span>
            <Track value={r.pct} color="var(--s0)" />
            <span className="num w-28 text-right">{chf(r.value, 0)} <span className="text-muted">· {r.aside}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------ countries */

export function Countries({ data }: P) {
  const rows = data.geo.rows.slice(0, 12);
  const top = rows[0]?.amount || 1;
  return (
    <Panel id="p-country" foldable defaultOpen={false} title="Dépenses par carte, par pays" hint="les virements n'ont pas de pays, seulement un IBAN">
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.country} className="grid grid-cols-[minmax(80px,140px)_minmax(0,1fr)_auto] items-center gap-3 text-[13px]">
            <span className="truncate">{r.country}</span>
            <Track value={(r.amount / top) * 100} color="var(--s0)" />
            <span className="num w-32 text-right">{chf(r.amount, 0)} <span className="text-muted">· {pct(r.share)}</span></span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------ custodian */

export function Custodian({ data }: P) {
  const c = data.custodian;
  let running = 0;
  const conv = c.conversions.map((x) => { running += x.markup_chf; return { ...x, running }; });
  const xs = conv.map((x) => day(x.date).getTime());
  const kpis = [
    ["Marge de change", `${chf(c.markup_chf)} CHF`],
    ["Taux effectif", `${c.effective_pct.toFixed(2)} %`],
    ["Volume converti", `${chf(c.volume_chf, 0)} CHF`],
    ["Intérêts débiteurs", `${chf(c.interest_chf)} CHF`],
    ["Frais explicites", `${chf(c.explicit_fees_chf)} CHF`],
  ];
  return (
    <Panel id="p-custodian" foldable defaultOpen={false} title="Ce que le custodian a prélevé"
           hint={`${chf(c.markup_chf)} CHF de marge sur ${plural(c.count, "conversion")}`}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {kpis.map(([k, v]) => (
          <div key={k} className="rounded-2xl bg-surface-2/60 p-3">
            <div className="eyebrow">{k}</div>
            <div className="num mt-1 text-[16px] font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[13.5px] text-ink-2">
        <b className="text-ink">La colonne « Frais et taxes » du relevé est vide.</b> Le coût est l'écart entre le taux de change
        affiché et le montant réellement débité : {c.median_markup_pct.toFixed(2)} % en médiane, stable d'une opération à l'autre —
        une marge tarifaire, pas un aléa de marché.
      </p>
      {c.references?.length > 0 && (
        <div className="mt-3 rounded-2xl bg-surface-2/50 p-3 text-[13px]">
          <b>Les mêmes conversions ailleurs</b> <span className="text-muted">— rejouées une à une, tarifs datés</span>
          <ul className="mt-1.5 space-y-1.5">
            {c.references.map((r) => (
              <li key={r.name}>
                <b>{r.name}</b> ({r.rate} %) : ≈ {chf(r.would_cost, 0)} CHF au lieu de {chf(c.markup_chf, 0)}
                <span className={r.saved > 0 ? "text-good" : "text-critical"}>{r.saved > 0 ? ` — ${chf(r.saved, 0)} CHF de moins` : " — plus cher"}</span>
                <span className="block text-[12px] text-muted">{r.note} · tarif lu le {r.as_of ?? c.references_as_of}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {xs.length > 1 && (
        <div className="mt-4">
          <Lines xs={xs} height={200}
                 series={[{ key: "m", name: "Marge cumulée", color: "var(--s1)", values: conv.map((x) => x.running), step: true }]}
                 xLabel={(i) => `${frDate(conv[i].date)} · ${conv[i].currency}`}
                 tipFormat={(v) => `${chf(v)} CHF`}
                 tipExtra={(i) => [
                   { name: "Montant crédité", value: `${chf(conv[i].foreign_amount)} ${conv[i].currency}` },
                   { name: "Réellement débité", value: `${chf(conv[i].charged_chf)} CHF` },
                   { name: "Marge", value: `${chf(conv[i].markup_chf)} · ${conv[i].markup_pct.toFixed(2)} %` },
                 ]}
                 xTicks={(w) => spreadTicks(xs.length, w, (i) => frDate(conv[i].date).slice(3), 80)}
                 ariaLabel="Cumul de la marge de change prélevée" />
        </div>
      )}
    </Panel>
  );
}

export { compact };
