/** Projects: a trip, a move, a wedding -- movements gathered under a name,
 * at what they really cost once the friends paid back their share. Stays
 * abroad are proposed as projects; nothing is gathered without a click, and
 * every change is undone from its toast. Figures are the server's
 * (`api/projects`). */
import { ArrowLeft, Check, Map, Minus, Pencil, Plane, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Field, Input } from "@/components/Form";
import { PageHeader } from "@/components/PageState";
import { Sheet } from "@/components/Sheet";
import { Button, Callout, Card, Dot, Note, Panel, Skeleton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { chf, frDate, frDay, plural } from "@/lib/format";
import { useView } from "@/lib/url";
import type { ProjectRow, ProjectSummary, ProjectsData, Suggestion } from "./projects/types";

const slotColor = (slot: number | null | undefined) => (slot != null ? `var(--s${slot})` : "var(--unsorted)");

type Undo = { undo: unknown; id: string };

async function act(body: unknown, message: string) {
  const r = await send<Undo>("/api/projets", body);
  toast(message, { action: { label: "Annuler", onClick: async () => { await send("/api/projets", r.undo); toast("Annulé"); } } });
  return r;
}

function span(p: { start: string | null; end: string | null; days: number }) {
  if (!p.start || !p.end) return "aucune ligne";
  return p.start === p.end ? frDate(p.start) : `${frDate(p.start)} → ${frDate(p.end)} · ${plural(p.days, "jour")}`;
}

export default function ProjectsPage() {
  const { params } = useView();
  const id = params.get("p");
  const q = new URLSearchParams();
  if (id) q.set("p", id);
  const { data, isPending, error } = useApi<ProjectsData>("/api/projets", q);
  if (error) return <Callout tone="bad" title="La page n'a pas pu être chargée">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-60 rounded-card" /></div>;
  if (data.empty) return <Callout title="Aucun relevé" />;
  if (id && data.detail) return <Detail data={data} />;
  return <List data={data} />;
}

/* ----------------------------------------------------------------- list */

function List({ data }: { data: ProjectsData }) {
  const [creating, setCreating] = useState(false);
  const max = Math.max(...data.projects.map((p) => p.net), 1);
  return (
    <div>
      <PageHeader
        title="Projets"
        subtitle="un voyage, un déménagement : ce qu'il a vraiment coûté, une fois les parts remboursées"
        actions={<Button size="sm" onClick={() => setCreating(true)}><Plus size={15} />Nouveau projet</Button>}
      />
      <div className="space-y-4 sm:space-y-5">
        {data.suggestions.length > 0 && <Suggestions rows={data.suggestions} />}
        {data.projects.length > 0 ? (
          <Panel id="p-projects" title="Tes projets" hint="du plus récent au plus ancien ; la barre compare leur coût net">
            <ul className="divide-y divide-hairline">
              {data.projects.map((p) => <ProjectLine key={p.id} p={p} max={max} />)}
            </ul>
          </Panel>
        ) : data.suggestions.length === 0 && (
          <Card className="p-8 text-center">
            <Map className="mx-auto text-muted" size={30} />
            <p className="mt-3 text-[14px] text-ink-2">Aucun projet. Un voyage à l'étranger est proposé tout seul ; pour le reste, « Nouveau projet ».</p>
          </Card>
        )}
      </div>
      <NewProject open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function ProjectLine({ p, max }: { p: ProjectSummary; max: number }) {
  const { href } = useView();
  return (
    <li>
      <Link to={href({ p: p.id }, { keep: ["p"] })} className="block py-3 no-underline hover:bg-surface-2/50 sm:-mx-2 sm:rounded-xl sm:px-2">
        <div className="flex items-baseline gap-3">
          <span className="min-w-0 flex-1 truncate text-[14.5px] font-semibold">{p.name}</span>
          <span className="num text-[15px] font-semibold">{chf(p.net, 0)}</span>
        </div>
        <div className="mt-0.5 flex items-baseline gap-3 text-[12px] text-muted">
          <span className="min-w-0 flex-1 truncate">{span(p)}{p.countries.length > 0 && ` · ${p.countries.join(", ")}`}</span>
          {p.back > 0 && <span className="num shrink-0 text-good">−{chf(p.back, 0)} remboursés</span>}
        </div>
        <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-surface-2" style={{ width: `${Math.max((p.net / max) * 100, 2)}%` }}>
          {p.categories.map((c) => <span key={c.category} style={{ width: `${c.share}%`, background: slotColor(c.slot) }} />)}
        </div>
      </Link>
    </li>
  );
}

function Suggestions({ rows }: { rows: Suggestion[] }) {
  const [open, setOpen] = useState<Suggestion | null>(null);
  return (
    <Panel id="p-suggestions" title="Voyages repérés" hint="des paiements sur place à l'étranger (repas, hôtel, courses), avec les vols et hôtels réservés avant et les parts remboursées après">
      <ul className="grid gap-3 md:grid-cols-2">
        {rows.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => setOpen(s)}
                    className="flex w-full items-center gap-3 rounded-2xl border border-hairline p-3.5 text-left transition hover:bg-surface-2/60">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-surface-2"><Plane size={18} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-semibold">{s.name}</span>
                <span className="block truncate text-[12px] text-muted">{frDay(s.start, false)} → {frDay(s.end)} · {plural(s.count, "ligne")} · net {chf(s.net, 0)} CHF</span>
              </span>
              <span className="shrink-0 text-[13px] font-medium text-accent">Voir</span>
            </button>
          </li>
        ))}
      </ul>
      <Note>Rien n'est rassemblé avant « Créer » : chaque proposition s'ouvre, dit pourquoi chaque ligne est là, et se corrige.</Note>
      <SuggestionSheet s={open} onClose={() => setOpen(null)} />
    </Panel>
  );
}

function SuggestionSheet({ s, onClose }: { s: Suggestion | null; onClose: () => void }) {
  const [name, setName] = useState("");
  const [off, setOff] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  if (s && shown !== s.id) { setShown(s.id); setName(s.name); setOff(new Set()); }
  const kept = s ? s.rows.filter((r) => !off.has(r.key)) : [];
  const toggle = (key: string) => setOff((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const create = async () => {
    if (!s) return;
    setBusy(true);
    try {
      await act({ action: "create", name, keys: kept.map((r) => r.key), kind: "voyage" }, `« ${name} » créé`);
      onClose();
    } finally { setBusy(false); }
  };
  const dismiss = async () => {
    if (!s) return;
    await act({ action: "dismiss", id: s.id }, "Proposition ignorée");
    onClose();
  };
  return (
    <Sheet open={!!s} onOpenChange={(o) => !o && onClose()} title={s?.name ?? ""} description={s?.why} wide
           footer={<div className="flex flex-wrap items-center gap-2">
             <Button variant="primary" onClick={create} disabled={busy || !kept.length || !name.trim()}>
               <Check size={15} />Créer avec {plural(kept.length, "ligne")}
             </Button>
             <Button variant="ghost" onClick={dismiss}>Ignorer ce voyage</Button>
           </div>}>
      {s && (
        <div className="space-y-4">
          <Field label="Nom du projet">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <div>
            <div className="eyebrow mb-1.5">Les lignes proposées · décoche ce qui n'en fait pas partie</div>
            <ul className="divide-y divide-hairline rounded-2xl border border-hairline">
              {s.rows.map((r) => {
                const on = !off.has(r.key);
                return (
                  <li key={r.key}>
                    <label className={cx("flex cursor-pointer items-center gap-3 px-3 py-2 text-[13.5px]", !on && "opacity-50")}>
                      <input type="checkbox" checked={on} onChange={() => toggle(r.key)} className="size-4 shrink-0 accent-[var(--ink)]" />
                      <span className="num w-12 shrink-0 text-[12px] text-muted">{frDate(r.date).slice(0, 5)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{r.label}</span>
                        <span className="block truncate text-[11.5px] text-muted">{r.reason} · {r.subcategory || r.category}</span>
                      </span>
                      <span className={cx("num shrink-0 font-medium", r.amount > 0 && "text-good")}>{r.amount > 0 ? "+" : ""}{chf(Math.abs(r.amount), 2)}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
          <Note className="mt-0">« Ignorer » ne propose plus ce séjour ; l'annulation du toast le fait revenir.</Note>
        </div>
      )}
    </Sheet>
  );
}

function NewProject({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { go } = useView();
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [err, setErr] = useState<string | undefined>();
  const submit = async () => {
    try {
      const r = await act({ action: "create", name, keys: [], start, end: end || start }, `« ${name} » créé`);
      onOpenChange(false); setName(""); setStart(""); setEnd(""); setErr(undefined);
      go({ p: r.id }, { keep: ["p"] });
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Nouveau projet"
           description="Un nom, et les dates autour desquelles chercher ses lignes."
           footer={<Button variant="primary" onClick={submit} disabled={!name.trim()}>Créer</Button>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label="Nom" error={err}>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="Déménagement, mariage de Léa…" autoFocus />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Du">{(id) => <Input id={id} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}</Field>
          <Field label="Au">{(id) => <Input id={id} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />}</Field>
        </div>
      </form>
    </Sheet>
  );
}

/* --------------------------------------------------------------- detail */

function Detail({ data }: { data: ProjectsData }) {
  const d = data.detail!;
  const { href, go } = useView();
  const [renaming, setRenaming] = useState<string | null>(null);
  const rename = async () => {
    if (renaming && renaming.trim() && renaming !== d.name) await act({ action: "rename", id: d.id, name: renaming }, "Renommé");
    setRenaming(null);
  };
  const remove = async () => {
    await act({ action: "delete", id: d.id }, `« ${d.name} » supprimé`);
    go({ p: null }, { keep: ["p"] });
  };
  const tiles = [
    { label: "Coût net", value: chf(d.net, 0), sub: "dépensé moins remboursé", tone: "" },
    { label: "Dépensé", value: chf(d.spent, 0), sub: plural(d.count, "ligne"), tone: "" },
    { label: "Remboursé", value: chf(d.back, 0), sub: d.back ? "les parts reçues" : "rien encore", tone: d.back ? "text-good" : "" },
    { label: "Par jour", value: d.per_day != null ? chf(d.per_day, 0) : "—", sub: d.days ? plural(d.days, "jour") : "", tone: "" },
  ];
  return (
    <div>
      <Link to={href({ p: null }, { keep: ["p"] })} className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-2 no-underline hover:text-ink">
        <ArrowLeft size={15} />Projets
      </Link>
      <PageHeader
        title={renaming != null ? (
          <form onSubmit={(e) => { e.preventDefault(); rename(); }}>
            <Input value={renaming} onChange={(e) => setRenaming(e.target.value)} onBlur={rename} autoFocus aria-label="Nom du projet" className="text-[20px] font-semibold" />
          </form>
        ) : (
          <button type="button" onClick={() => setRenaming(d.name)} className="group inline-flex items-center gap-2 text-left">
            {d.name}<Pencil size={16} className="text-muted opacity-60 group-hover:opacity-100" />
          </button>
        )}
        subtitle={<>{span(d)}{d.countries.length > 0 && ` · ${d.countries.join(", ")}`}</>}
        actions={<Button size="sm" variant="ghost" onClick={remove}><Trash2 size={15} />Supprimer</Button>}
      />
      <div className="space-y-4 sm:space-y-5">
        <Card className="p-4 sm:p-5">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {tiles.map((t) => (
              <div key={t.label} className="min-w-0">
                <div className="eyebrow">{t.label}</div>
                <div className={cx("num mt-1 text-[22px] font-semibold tracking-[-0.02em]", t.tone)}>{t.value}</div>
                <div className="truncate text-[12px] text-muted">{t.sub}</div>
              </div>
            ))}
          </div>
          {d.categories.length > 0 && (
            <div className="mt-4">
              <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full">
                {d.categories.map((c) => <span key={c.category} style={{ width: `${c.share}%`, background: slotColor(c.slot) }} className="h-full min-w-[2px]" />)}
              </div>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-2">
                {d.categories.map((c) => (
                  <li key={c.category} className="inline-flex items-center gap-1.5"><Dot color={slotColor(c.slot)} />{c.category} <span className="num text-muted">{chf(c.amount, 0)}</span></li>
                ))}
              </ul>
            </div>
          )}
        </Card>
        <Panel id="p-rows" title="Les lignes du projet" hint="une ligne retirée reste dans le relevé, seulement hors du projet">
          {d.rows.length ? (
            <ul className="divide-y divide-hairline">
              {d.rows.map((r) => <Row key={r.key} r={r} action={
                <button type="button" aria-label={`Retirer ${r.label}`} onClick={() => act({ action: "remove", id: d.id, keys: [r.key] }, "Ligne retirée")}
                        className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-critical"><Minus size={15} /></button>
              } />)}
            </ul>
          ) : <p className="text-[13px] text-muted">Aucune ligne encore : ajoute-les ci-dessous.</p>}
          {d.missing > 0 && <Note>{plural(d.missing, "ligne")} du projet n'est plus dans le relevé (import oublié).</Note>}
        </Panel>
        <Candidates id={d.id} rows={d.candidates} />
      </div>
    </div>
  );
}

function Row({ r, action }: { r: ProjectRow; action: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3 py-2 text-[13.5px]">
      <span className="num w-[4.5rem] shrink-0 text-[12.5px] text-muted">{frDate(r.date).slice(0, 5)}.{frDate(r.date).slice(8)}</span>
      <Dot color={r.amount > 0 ? "var(--good)" : slotColor(r.slot)} />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{r.label}</span>
        <span className="block truncate text-[11.5px] text-muted">{r.amount > 0 ? "remboursement" : r.subcategory || r.category}{r.country && ` · ${r.country}`}</span>
      </span>
      <span className={cx("num shrink-0 font-medium", r.amount > 0 && "text-good")}>{r.amount > 0 ? "+" : ""}{chf(Math.abs(r.amount), 2)}</span>
      {action}
    </li>
  );
}

function Candidates({ id, rows }: { id: string; rows: ProjectRow[] }) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  if (!rows.length) return null;
  const needle = q.trim().toLowerCase();
  const found = needle ? rows.filter((r) => `${r.label} ${r.category} ${r.country ?? ""}`.toLowerCase().includes(needle)) : rows;
  const shown = all || needle ? found : found.slice(0, 12);
  return (
    <Panel id="p-add" title="Ajouter des lignes" hint="les mouvements du mois autour du projet ; un remboursement reçu se compte en moins">
      <label className="relative mb-2 block">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chercher un commerçant, une catégorie…" className="pl-9" aria-label="Chercher une ligne" />
      </label>
      <ul className="divide-y divide-hairline">
        {shown.map((r) => <Row key={r.key} r={r} action={
          <button type="button" aria-label={`Ajouter ${r.label}`} onClick={() => act({ action: "add", id, keys: [r.key] }, "Ligne ajoutée")}
                  className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-good"><Plus size={15} /></button>
        } />)}
      </ul>
      {!needle && found.length > shown.length && (
        <button type="button" onClick={() => setAll(true)} className="mt-2 text-[13px] font-medium text-accent hover:underline">
          Les {found.length} lignes
        </button>
      )}
    </Panel>
  );
}
