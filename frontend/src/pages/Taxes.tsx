/** The tax return, as far as the statement can fill it: each deduction with
 * the federal rule that makes it one and the lines behind it, the pay, the
 * interest, the wealth on 31 December, the tax paid in the year. Every
 * figure is the server's (`api/taxes`); the certificates stay the authority. */
import { ChevronDown, Download, FileCheck2 } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { Field, Input, Select } from "@/components/Form";
import { PageHeader } from "@/components/PageState";
import { TaxReserve } from "@/components/TaxProvision";
import { Button, Callout, Card, Note, Panel, Reveal, Segmented, Skeleton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, frDate, plural } from "@/lib/format";
import { useView } from "@/lib/url";
import type { TaxItem, TaxLine, Taxes } from "./taxes/types";
import { Securities } from "./taxes/Securities";

const KEEP = ["year", "net"] as const;

const CERTAINTY: Record<TaxItem["certainty"], { label: string; tone: string }> = {
  exact: { label: "exact", tone: "bg-[color-mix(in_srgb,var(--good)_12%,transparent)] text-good" },
  rule: { label: "forfait", tone: "bg-surface-2 text-ink-2" },
  estimate: { label: "estimé", tone: "bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] text-warn" },
  indicative: { label: "à trier", tone: "bg-surface-2 text-muted" },
};

export default function TaxesPage() {
  const { params, href } = useView();
  const q = new URLSearchParams();
  KEEP.forEach((k) => { const v = params.get(k); if (v) q.set(k, v); });
  const { data, isPending, isPlaceholderData, error } = useApi<Taxes>("/api/impots", q);
  if (error) return <Callout tone="bad" title="La page n'a pas pu être chargée">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-28 rounded-card" /><Skeleton className="h-72 rounded-card" /></div>;
  if (data.empty) return <Callout title="Aucun relevé" />;
  const net = params.get("net");
  const found = data.items.filter((i) => i.amount > 0);
  const nothing = data.items.filter((i) => i.amount <= 0);

  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <PageHeader
        title="Impôts"
        subtitle={<>ce que le relevé apporte à la déclaration {data.year}, à remplir au printemps {data.year + 1}</>}
        actions={<>
          <Segmented size="sm" label="Année" value={data.year}
                     options={data.years.map((y) => ({ id: y, label: String(y) }))}
                     hrefFor={(y) => href({ year: String(y) }, { keep: KEEP })} />
          <a href={`/impots/${data.year}.xlsx${net ? `?net=${encodeURIComponent(net)}` : ""}`} download
             className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink">
            <Download size={15} />Excel
          </a>
        </>}
      />
      <div className="space-y-4 sm:space-y-5">
        {!data.whole && (
          <Callout tone="warn" title={`${data.year} n'est pas entière dans le relevé`}>
            Les montants ne couvrent que les mois du relevé : une estimation, pas l'année.
          </Callout>
        )}
        <Headline data={data} />
        <CantonCard data={data} />
        <NetIncome data={data} />
        <Panel id="p-deductions" title="Déductions"
               hint={data.canton ? `ce que le relevé montre, et ce qu'en déduisent l'impôt fédéral et ${data.canton.name}` : "ce que le relevé montre, et ce que la règle fédérale en déduit"}>
          <ul className="space-y-2.5">
            {found.map((i) => <Item key={i.key} item={i} canton={data.canton?.name} />)}
          </ul>
          {nothing.length > 0 && (
            <p className="mt-3 text-[12.5px] text-muted">
              Rien trouvé pour : {nothing.map((i) => i.title.toLowerCase()).join(", ")}. Une ligne mal reconnue se classe
              dans <Link to="/corrections" className="text-accent">Corrections</Link>.
            </p>
          )}
          <Note>
            Règles de l'impôt fédéral direct pour une personne salariée{data.published ? "" : " (montants de la dernière année connue)"}
            {data.canton ? <>, et celles de {data.canton.name} (<a href={data.canton.guide} target="_blank" rel="noreferrer" className="text-accent">guide fiscal</a>) ; une règle cantonale marquée « à vérifier » n'a pas été lue dans le guide de l'année. </> : " ; ton canton a les siennes : indique-le ci-dessus. "}
            Les frais de garde, le 2e pilier et les frais professionnels forfaitaires ne se lisent pas dans un relevé.
          </Note>
        </Panel>
        <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
          <Income data={data} />
          <Wealth data={data} />
        </div>
        <Securities data={data} />
        <Paid data={data} />
        {data.provision && (
          <Panel id="p-provision" title="À mettre de côté" hint="les impôts des années pas encore réglées, estimés au taux déjà payé">
            <TaxReserve p={data.provision} className="!border-0 !p-0" />
            <Note>Prévisions le compare à ce que la prévision du cash paie déjà, et peut en faire le seuil d'alerte.</Note>
          </Panel>
        )}
      </div>
    </div>
  );
}

function Headline({ data }: { data: Taxes }) {
  const pay = data.salaries.length > 0;
  const tiles = [
    data.canton && data.deducted_canton != null
      ? { label: "Déductions repérées", value: `≈ ${chf(data.deducted_canton, 0)}`, sub: `${data.canton.name} · ${chf(data.deducted, 0)} au fédéral` }
      : { label: "Déductions repérées", value: `≈ ${chf(data.deducted, 0)}`, sub: "CHF, impôt fédéral" },
    { label: "3a versé", value: chf(data.pillar3a.paid, 0), sub: `sur ${chf(data.pillar3a.ceiling, 0)} possibles` },
    { label: `Fortune au ${frDate(data.wealth.day).slice(0, 5)}`, value: chf(data.wealth.taxable, 0), sub: data.wealth.partial ? "estimation, l'année court encore" : "ces comptes" },
    { label: data.paid.later ? `Impôts ${data.year}` : "Impôts payés",
      value: data.paid.later && !data.paid.seen ? "—" : chf(data.paid.out, 0),
      sub: data.paid.later ? (data.paid.seen ? `payés en ${data.paid.year}` : `se paieront en ${data.paid.year}`)
        : data.paid.back ? `${chf(data.paid.back, 0)} remboursés` : "dans l'année" },
  ];
  return (
    <Card className="p-4 sm:p-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="min-w-0">
            <div className="eyebrow">{t.label}</div>
            <div className="num mt-1 text-[22px] font-semibold tracking-[-0.02em]">{t.value}</div>
            <div className="truncate text-[12px] text-muted">{t.sub}</div>
          </div>
        ))}
      </div>
      {!pay && <Note>Aucun salaire régulier n'est lu cette année : les seuils en pourcent du revenu se calculent sur le revenu net déclaré ci-dessous.</Note>}
    </Card>
  );
}

function NetIncome({ data }: { data: Taxes }) {
  const { go } = useView();
  const [typed, setTyped] = useState<string | null>(null);
  const apply = () => {
    if (typed == null) return;
    const v = typed.replace(/['’\s]/g, "");
    go({ net: v || null }, { keep: KEEP, replace: true });
    setTyped(null);
  };
  return (
    <Card className="flex flex-wrap items-end gap-x-5 gap-y-3 p-4 sm:p-5">
      <div className="w-full max-w-[14rem]">
        <Field label="Revenu net (pour les seuils)">
          {(id) => (
            <Input id={id} inputMode="decimal" value={typed ?? chf(data.net.value, 0)}
                   onChange={(e) => setTyped(e.target.value)} onBlur={apply}
                   onKeyDown={(e) => { if (e.key === "Enter") apply(); }} />
          )}
        </Field>
      </div>
      <p className="min-w-0 flex-1 basis-64 text-[12.5px] leading-snug text-muted">
        {data.net.estimated
          ? <>Estimé : le salaire versé ({chf(data.net.pay, 0)} CHF) moins le 3a. Le revenu net de ta dernière taxation est plus juste : tape-le, frais médicaux et dons en dépendent.</>
          : <>Déclaré. Vide le champ pour revenir à l'estimation tirée du salaire versé.</>}
      </p>
    </Card>
  );
}

function Item({ item, canton }: { item: TaxItem; canton?: string }) {
  const [open, setOpen] = useState(false);
  const c = CERTAINTY[item.certainty];
  return (
    <li className="rounded-2xl border border-hairline">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
              className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 p-3.5 text-left sm:p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[14.5px] font-semibold">{item.title}</span>
            <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-medium", c.tone)}>{c.label}</span>
          </div>
          <div className="mt-0.5 truncate text-[12px] text-muted">{item.form}</div>
        </div>
        <div className="text-right">
          {item.canton ? (
            <div className="flex items-baseline justify-end gap-3">
              <span><span className="block text-[10.5px] uppercase tracking-wide text-muted">fédéral</span>
                <span className="num text-[15px] font-semibold">{item.deductible != null ? chf(item.deductible, 0) : "—"}</span></span>
              <span><span className="block text-[10.5px] uppercase tracking-wide text-muted">{canton}</span>
                <span className="num text-[15px] font-semibold">{chf(item.canton.deductible, 0)}</span></span>
            </div>
          ) : (
            <div className="num text-[16px] font-semibold">{item.deductible != null ? chf(item.deductible, 0) : "—"}</div>
          )}
          <div className="num text-[11.5px] text-muted">{item.deductible != null || item.canton ? "déductible" : "à trier"} · relevé {chf(item.amount, 0)}</div>
        </div>
        <p className="col-span-2 text-[12.5px] leading-snug text-ink-2">
          {item.canton && <b className="font-medium text-ink">Fédéral : </b>}{item.rule}{item.note && <> {item.note}</>}
        </p>
        {item.canton && (
          <p className="col-span-2 -mt-0.5 text-[12.5px] leading-snug text-ink-2">
            <b className="font-medium text-ink">{canton} : </b>{item.canton.rule}
            {!item.canton.certain && <span className="ml-1.5 rounded-full bg-surface-2 px-1.5 py-0.5 text-[10.5px] text-muted">à vérifier</span>}
          </p>
        )}
        {item.rows.length > 0 && (
          <span className="col-span-2 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent">
            <ChevronDown size={14} className={cx("transition-transform", !open && "-rotate-90")} />
            {plural(item.rows.length, "ligne")}
          </span>
        )}
      </button>
      {open && <Lines rows={item.rows} />}
    </li>
  );
}

function Lines({ rows }: { rows: TaxLine[] }) {
  return (
    <ul className="max-h-80 divide-y divide-hairline overflow-y-auto border-t border-hairline px-3.5 text-[13px] sm:px-4">
      {rows.map((r, i) => (
        <li key={(r.key ?? r.label) + i} className="flex items-center gap-3 py-1.5">
          <span className="num w-20 shrink-0 text-muted">{frDate(r.date)}</span>
          <span className="min-w-0 flex-1 truncate">{r.label}</span>
          <span className={cx("num shrink-0", r.amount < 0 && "text-good")}>{chf(r.amount, 2)}</span>
        </li>
      ))}
    </ul>
  );
}

function Income({ data }: { data: Taxes }) {
  const i = data.interest;
  return (
    <Panel id="p-income" title="Revenus" hint="ce qui est entré, à rapprocher des attestations">
      {data.salaries.length > 0 ? (
        <ul className="divide-y divide-hairline text-[13.5px]">
          {data.salaries.map((p) => (
            <li key={p.label} className="flex items-center gap-3 py-2">
              <FileCheck2 size={15} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate">{p.label}</span>
              <span className="text-[12px] text-muted">{plural(p.count, "versement")}</span>
              <span className="num font-semibold">{chf(p.amount, 0)}</span>
            </li>
          ))}
        </ul>
      ) : <p className="text-[13px] text-muted">Aucun salaire régulier lu dans l'année.</p>}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px]">
        <dt className="text-muted">Intérêts bancaires</dt><dd className="num text-right">{chf(i.bank, 2)}</dd>
        <dt className="text-muted">Dividendes IBKR</dt><dd className="num text-right">{chf(i.dividends, 2)}</dd>
        <dt className="text-muted">Intérêts IBKR</dt><dd className="num text-right">{chf(i.broker, 2)}</dd>
        <dt className="text-muted">Impôt US retenu (DA-1)</dt><dd className="num text-right">{chf(i.withheld, 2)}</dd>
        {data.securities.filter((s) => s.dividends.net).map((s) => (
          <Fragment key={s.id}>
            <dt className="truncate text-muted">Dividende brut · {s.name}</dt>
            <dd className="num text-right">{chf(s.dividends.gross, 2)}</dd>
          </Fragment>
        ))}
      </dl>
      <Note>Le salaire est le net versé : le certificat de salaire donne le brut à déclarer.</Note>
    </Panel>
  );
}

function Wealth({ data }: { data: Taxes }) {
  const { pageHref } = useView();
  const w = data.wealth;
  return (
    <Panel id="p-wealth" title={`Fortune au ${frDate(w.day)}`} hint={w.partial ? "estimation : l'année n'est pas finie" : "compte par compte"}
           actions={<Link to={pageHref("/epargne")} className="text-[13px] font-medium text-accent no-underline hover:underline">Épargne</Link>}>
      <ul className="divide-y divide-hairline text-[13.5px]">
        {w.rows.map((r) => (
          <li key={r.name} className="flex items-center gap-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate">{r.name}</span>
              {r.detail && <span className="block truncate text-[11.5px] text-muted">{r.detail}</span>}
            </span>
            <span className="num font-medium">{r.value != null ? chf(r.value, 0) : "—"}</span>
          </li>
        ))}
        <li className="flex items-center gap-3 py-2 font-semibold">
          <span className="flex-1">Fortune imposable, ces comptes</span>
          <span className="num">{chf(w.taxable, 0)}</span>
        </li>
      </ul>
      {w.pillar3a_value != null && <Note>Le 3a ({chf(w.pillar3a_value, 0)} CHF) n'entre pas dans la fortune imposable avant son retrait.</Note>}
      <Note>Valeurs de l'app : l'AFC valorise titres et devises à ses propres cours de fin d'année, proches, pas identiques.</Note>
    </Panel>
  );
}

function Paid({ data }: { data: Taxes }) {
  if (data.paid.later && !data.paid.seen) {
    return (
      <Panel id="p-paid" title={`Impôts ${data.year}`} hint={`ils se paient en ${data.paid.year}`}>
        <p className="text-[13px] text-muted">Le relevé n'atteint pas encore {data.paid.year} : la page les montrera quand ils seront payés.</p>
      </Panel>
    );
  }
  if (!data.paid.rows.length) return null;
  return (
    <Panel id="p-paid" title={data.paid.later ? `Impôts ${data.year}, payés en ${data.paid.year}` : "Impôts payés dans l'année"}
           hint="acomptes, décomptes et remboursements, tels que le relevé les montre">
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <div><div className="eyebrow">Payé</div><div className="num text-[20px] font-semibold">{chf(data.paid.out, 0)}</div></div>
        {data.paid.back > 0 && <div><div className="eyebrow">Remboursé</div><div className="num text-[20px] font-semibold text-good">{chf(data.paid.back, 0)}</div></div>}
      </div>
      <Reveal className="mt-2" summary={plural(data.paid.rows.length, "ligne")}>
        <div className="-mx-4 sm:-mx-5"><Lines rows={data.paid.rows} /></div>
      </Reveal>
    </Panel>
  );
}

function CantonCard({ data }: { data: Taxes }) {
  const s = data.settings;
  const [editing, setEditing] = useState(!s.canton);
  const [canton, setCanton] = useState(s.canton);
  const [since, setSince] = useState(String(s.since ?? Math.max(...data.years)));
  const [later, setLater] = useState(s.paid_next_year);
  const [busy, setBusy] = useState(false);
  const years = [...new Set([...data.years, Math.max(...data.years) + 1])].sort((a, b) => b - a);
  const save = async () => {
    setBusy(true);
    try {
      await send("/api/impots/reglages", { canton, since: canton ? Number(since) : null, paid_next_year: canton ? later : false });
      setEditing(false);
    } finally { setBusy(false); }
  };
  const name = data.cantons.find((c) => c.id === s.canton)?.name;
  if (!editing && s.canton) {
    return (
      <Card className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4 text-[13.5px] sm:px-5">
        <span><b>{name}</b> depuis {s.since}{s.paid_next_year ? " · l'impôt d'une année se paie l'année suivante" : ""}</span>
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Modifier</Button>
      </Card>
    );
  }
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 text-[14px] font-semibold">Où déclares-tu ?</div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-44"><Field label="Canton">{(id) => (
          <Select id={id} value={canton} onChange={(e) => setCanton(e.target.value)}>
            <option value="">Impôt fédéral seulement</option>
            {data.cantons.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        )}</Field></div>
        {canton && <div className="w-32"><Field label="Depuis l'année">{(id) => (
          <Select id={id} value={since} onChange={(e) => setSince(e.target.value)}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        )}</Field></div>}
        {canton && (
          <label className="flex h-10 items-center gap-2 text-[13px]">
            <input type="checkbox" checked={later} onChange={(e) => setLater(e.target.checked)} className="size-4 accent-[var(--ink)]" />
            L'impôt d'une année se paie l'année suivante
          </label>
        )}
        <Button variant="primary" onClick={save} disabled={busy}>Enregistrer</Button>
      </div>
      <Note>Seul Genève a ses règles dans l'app ; un autre canton garde celles de l'impôt fédéral.</Note>
    </Card>
  );
}
