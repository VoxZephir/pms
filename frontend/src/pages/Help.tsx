/** The user's manual: what each page answers, how to move in time, how to
 * read and handle a chart, how to correct a category, the keys. The charts
 * here are the app's own (`charts/`), drawn on invented numbers -- a reader
 * tries the gestures on the real thing, and no figure of theirs is shown. */
import { ArrowRight, FileText, Hand, LayoutGrid, MousePointer2, ShieldCheck, Tags } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { CalendarHeat } from "@/charts/Calendar";
import { Columns, type Column } from "@/charts/Columns";
import { Lines, spreadTicks } from "@/charts/Lines";
import { PageHeader } from "@/components/PageState";
import { Card, Dot, Panel, Reveal, Segmented, cx } from "@/components/ui";
import { MONTHS, MONTHS_SHORT, chf, iso } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { goToSection } from "@/shell/Sections";
import { NAV, UPLOAD, helpAnchor } from "@/shell/nav";

/* ------------------------------------------------------------ helpers */

/** The same invented numbers at every visit: a seeded generator. */
function seeded(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex min-w-[1.6em] items-center justify-center rounded-md border border-hairline-2 bg-surface px-1.5 py-0.5 text-[12px] font-medium text-ink shadow-[0_1px_0_var(--hairline-2)]">
      {children}
    </kbd>
  );
}

function Try({ children }: { children: ReactNode }) {
  return (
    <p className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-ink-2">
      <MousePointer2 size={13} />{children}
    </p>
  );
}

function Prose({ children }: { children: ReactNode }) {
  return <div className="max-w-[75ch] space-y-2.5 text-[14px] leading-relaxed text-ink-2 [&_b]:font-semibold [&_b]:text-ink">{children}</div>;
}

function useReduced() {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/* ------------------------------------------------- 1. how data comes in */

const FLOW = [
  { icon: FileText, title: "Un relevé", text: "PDF Swissquote ou UBS, CSV Revolut, camt.053 : déposé sur « Importer », ou simplement téléchargé sur le PC." },
  { icon: ShieldCheck, title: "Vérifié", text: "Les soldes imprimés sont rechaînés ligne à ligne : une ligne perdue casse la chaîne et l'app le dit." },
  { icon: Tags, title: "Classé", text: "Règles de commerçants, tes règles personnelles, tes corrections : chaque mouvement prend sa catégorie." },
  { icon: LayoutGrid, title: "Lu", text: "Chaque page calcule sur le même ledger : un chiffre est le même partout." },
];

function Flow() {
  const reduced = useReduced();
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const t = window.setInterval(() => setStep((s) => (s + 1) % FLOW.length), 1600);
    return () => window.clearInterval(t);
  }, [reduced]);
  return (
    <ol className="grid gap-3 sm:grid-cols-4">
      {FLOW.map((f, i) => {
        const lit = reduced || i <= step;
        return (
          <li key={f.title} className="relative">
            <motion.div
              animate={{ scale: !reduced && i === step ? 1.03 : 1, opacity: lit ? 1 : 0.45 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}
              className={cx("h-full rounded-2xl border p-3.5 transition-colors",
                !reduced && i === step ? "border-s0 bg-[color-mix(in_srgb,var(--s0)_8%,var(--surface))]" : "border-hairline bg-surface")}>
              <div className="mb-2 flex items-center gap-2">
                <span className={cx("grid size-7 place-items-center rounded-lg", lit ? "bg-ink text-page" : "bg-surface-2 text-muted")}>
                  <f.icon size={15} />
                </span>
                <span className="text-[14px] font-semibold text-ink">{i + 1}. {f.title}</span>
              </div>
              <p className="text-[12.5px] leading-snug text-muted">{f.text}</p>
            </motion.div>
            {i < FLOW.length - 1 && (
              <ArrowRight size={14} className="absolute -right-[13px] top-1/2 hidden -translate-y-1/2 text-muted sm:block" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------- 2. the period */

type DemoGrain = "month" | "quarter" | "year";
const YEAR = 2025;

function periodOf(grain: DemoGrain, index: number) {
  if (grain === "year") return { title: `Année ${YEAR + index}`, from: `${YEAR + index}-01-01`, to: `${YEAR + index}-12-31`, inner: "month" };
  const per = grain === "quarter" ? 3 : 1;
  const total = 12 / per;
  const y = YEAR + Math.floor(index / total);
  const k = ((index % total) + total) % total;
  const m0 = k * per;
  const last = new Date(y, m0 + per, 0).getDate();
  const from = `${y}-${String(m0 + 1).padStart(2, "0")}-01`;
  const to = `${y}-${String(m0 + per).padStart(2, "0")}-${last}`;
  return grain === "quarter"
    ? { title: `${k + 1}${k ? "e" : "er"} trimestre ${y}`, from, to, inner: "week" }
    : { title: `${MONTHS[m0][0].toUpperCase()}${MONTHS[m0].slice(1)} ${y}`, from, to, inner: "day" };
}

function PeriodDemo() {
  const [grain, setGrain] = useState<DemoGrain>("month");
  const [index, setIndex] = useState(4);
  const [dir, setDir] = useState(1);
  const p = periodOf(grain, index);
  const go = (d: number) => { setDir(d); setIndex((i) => i + d); };
  const up = () => {
    if (grain === "month") { setGrain("year"); setIndex(0); } else if (grain === "quarter") { setGrain("year"); setIndex(0); }
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); go(-1); }
    if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); go(1); }
    if (e.key === "Escape") { e.stopPropagation(); up(); }
  };
  const crumbs = grain === "year" ? ["Tout", p.title] : ["Tout", `Année ${p.from.slice(0, 4)}`, p.title];
  return (
    <div tabIndex={0} onKeyDown={key} aria-label="Démonstration de la période : flèches gauche et droite, Échap pour remonter"
         className="rounded-2xl border border-hairline bg-surface-2/50 p-4 outline-none focus-visible:ring-2 focus-visible:ring-s0">
      <Try>Clique dans la boîte puis essaie <Kbd>←</Kbd> <Kbd>→</Kbd> et <Kbd>Échap</Kbd></Try>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => go(-1)} aria-label="Période précédente"
                className="grid size-9 place-items-center rounded-xl border border-hairline-2 bg-surface text-ink hover:bg-surface-2">‹</button>
        <div className="relative h-8 min-w-[12rem] flex-1 overflow-hidden">
          <AnimatePresence initial={false} custom={dir} mode="popLayout">
            <motion.div key={p.title} custom={dir}
                        initial={{ x: dir * 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: -dir * 40, opacity: 0 }}
                        transition={{ duration: 0.22 }}
                        className="absolute inset-0 flex items-center text-[18px] font-semibold tracking-tight text-ink">
              {p.title}
            </motion.div>
          </AnimatePresence>
        </div>
        <button type="button" onClick={() => go(1)} aria-label="Période suivante"
                className="grid size-9 place-items-center rounded-xl border border-hairline-2 bg-surface text-ink hover:bg-surface-2">›</button>
        <Segmented<DemoGrain> label="Unité de la démonstration" size="sm" value={grain}
                   onChange={(g) => { setGrain(g); setIndex(g === "year" ? 0 : g === "quarter" ? 1 : 4); }}
                   options={[{ id: "month", label: "Mois" }, { id: "quarter", label: "Trimestre" }, { id: "year", label: "Année" }]} />
      </div>
      <div className="mt-3 text-[12.5px] text-muted">
        {crumbs.map((c, i) => (
          <span key={c}>{i > 0 && <span className="mx-1.5">›</span>}<span className={i === crumbs.length - 1 ? "font-medium text-ink" : ""}>{c}</span></span>
        ))}
      </div>
      <code className="mt-2 block overflow-x-auto whitespace-nowrap rounded-lg bg-surface px-2.5 py-1.5 text-[12px] text-ink-2">
        /?from=<b className="text-s0">{p.from}</b>&amp;to=<b className="text-s0">{p.to}</b>&amp;grain=<b className="text-s0">{p.inner}</b>
      </code>
    </div>
  );
}

/* ------------------------------------------------------- 3. the columns */

const CATS = [
  { name: "Logement", color: "var(--s0)", base: 1900, spread: 0 },
  { name: "Alimentation", color: "var(--s2)", base: 620, spread: 220 },
  { name: "Loisirs & voyages", color: "var(--s1)", base: 300, spread: 900 },
];

function demoColumns(): Column[] {
  const rnd = seeded(7);
  return MONTHS_SHORT.map((m, i) => {
    const segments = CATS.map((c) => ({ name: c.name, color: c.color, value: Math.round(c.base + rnd() * c.spread + (c.name.startsWith("Loisirs") && (i === 6 || i === 11) ? 1400 : 0)) }));
    return { key: `m${i}`, label: `${MONTHS[i]} ${YEAR}`, short: m, segments, total: segments.reduce((a, s) => a + s.value, 0) };
  });
}

function median(values: number[]) {
  const s = [...values].sort((a, b) => a - b);
  const k = Math.floor(s.length / 2);
  return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2;
}

function GestureHint({ show }: { show: boolean }) {
  const reduced = useReduced();
  if (!show || reduced) return null;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      <motion.div className="absolute top-[18%] h-[62%] rounded-lg border border-s0/50 bg-[color-mix(in_srgb,var(--s0)_12%,transparent)]"
                  style={{ left: "38%" }}
                  animate={{ width: ["0%", "0%", "26%", "26%", "0%"], opacity: [0, 1, 1, 0, 0] }}
                  transition={{ duration: 3.2, repeat: Infinity, times: [0, 0.15, 0.6, 0.85, 1] }} />
      <motion.div className="absolute top-[45%] text-ink drop-shadow"
                  animate={{ left: ["38%", "38%", "64%", "64%", "38%"], scale: [1, 0.85, 0.85, 1, 1] }}
                  transition={{ duration: 3.2, repeat: Infinity, times: [0, 0.15, 0.6, 0.85, 1] }}>
        <Hand size={26} fill="var(--surface)" />
      </motion.div>
    </div>
  );
}

function ColumnsDemo() {
  const columns = useMemo(demoColumns, []);
  const [said, setSaid] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [withMedian, setWithMedian] = useState(false);
  const mid = median(columns.map((c) => c.total));
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Try>Survole, clique une colonne, ou glisse sur plusieurs</Try>
        <button type="button" aria-pressed={withMedian} onClick={() => setWithMedian((v) => !v)}
                className={cx("mb-3 rounded-full border px-2.5 py-1 text-[12px] font-medium transition",
                  withMedian ? "border-ink bg-ink text-page" : "border-hairline-2 text-ink-2 hover:bg-surface-2")}>
          Médiane
        </button>
      </div>
      <div className="relative" onPointerDownCapture={() => setTouched(true)}>
        <Columns columns={columns} height={220} ariaLabel="Démonstration : dépense par mois, chiffres inventés"
                 pickHint="Cliquer : ouvrir ce mois"
                 onPick={(c) => setSaid(`Ce clic ouvrirait ${c.label}, découpé par jour.`)}
                 onBrush={(a, b) => setSaid(`Ce glissé ouvrirait la fenêtre de ${columns[a].label} à ${columns[b].label}.`)}
                 reference={withMedian ? mid : undefined}
                 referenceLabel={withMedian ? `Médiane ${chf(mid, 0)}` : undefined} />
        <GestureHint show={!touched} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-ink-2">
        {CATS.map((c) => <span key={c.name} className="inline-flex items-center gap-1.5"><Dot color={c.color} />{c.name}</span>)}
      </div>
      <AnimatePresence mode="wait">
        {said && (
          <motion.p key={said} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    className="mt-3 rounded-xl bg-surface-2 px-3 py-2 text-[13px] text-ink">{said}</motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------ 4. the calendar */

function CalendarDemo() {
  const daily = useMemo(() => {
    const rnd = seeded(11);
    const out: Record<string, [number, number]> = {};
    const d = new Date(YEAR, 0, 1);
    const end = new Date(YEAR, 5, 30);
    while (d <= end) {
      const r = rnd();
      const weekend = d.getDay() === 0 || d.getDay() === 6;
      if (r > 0.18) {
        const amount = Math.round((weekend ? 60 : 25) + rnd() * (weekend ? 180 : 70) + (r > 0.97 ? 600 : 0));
        out[iso(d)] = [amount, 1 + Math.floor(rnd() * 4)];
      }
      d.setDate(d.getDate() + 1);
    }
    return out;
  }, []);
  const [said, setSaid] = useState<string | null>(null);
  return (
    <div>
      <Try>Survole un jour, clique-le</Try>
      <CalendarHeat daily={daily} start={`${YEAR}-01-01`} end={`${YEAR}-06-30`}
                    onPick={(d) => setSaid(`Ce clic ouvrirait la journée du ${d.split("-").reverse().join(".")} : chaque mouvement, le solde du soir.`)} />
      {said && <p className="mt-3 rounded-xl bg-surface-2 px-3 py-2 text-[13px] text-ink">{said}</p>}
    </div>
  );
}

/* --------------------------------------------------------- 5. the lines */

function LinesDemo() {
  const n = 25;
  const today = 12;
  const { measured, projected, low, high } = useMemo(() => {
    const rnd = seeded(5);
    const m: (number | null)[] = [];
    const p: (number | null)[] = [];
    const lo: (number | null)[] = [];
    const hi: (number | null)[] = [];
    let v = 40000;
    for (let i = 0; i < n; i++) {
      if (i <= today) {
        v = v * (1 + (rnd() - 0.4) * 0.05) + 600;
        m.push(Math.round(v));
        p.push(i === today ? Math.round(v) : null);
        lo.push(i === today ? Math.round(v) : null);
        hi.push(i === today ? Math.round(v) : null);
      } else {
        const k = i - today;
        const mid = (p[i - 1] as number) * 1.004 + 600;
        p.push(Math.round(mid));
        m.push(null);
        lo.push(Math.round(mid - 1500 * Math.sqrt(k)));
        hi.push(Math.round(mid + 1500 * Math.sqrt(k)));
      }
    }
    return { measured: m, projected: p, low: lo, high: hi };
  }, []);
  const label = (i: number) => {
    const m = i % 12;
    return `${MONTHS_SHORT[m]} ${String(YEAR + Math.floor(i / 12)).slice(2)}`;
  };
  return (
    <div>
      <Try>Survole la courbe : mesuré à gauche du trait, projeté à droite</Try>
      <Lines xs={Array.from({ length: n }, (_, i) => i)} height={220} zero={false}
             series={[
               { key: "m", name: "Mesuré", color: "var(--s0)", values: measured, width: 2.5, area: true },
               { key: "p", name: "Projeté", color: "var(--s0)", values: projected, width: 2, dash: true },
             ]}
             band={{ low, high, color: "var(--s0)" }}
             todayIndex={today}
             tipFormat={(v) => `${chf(v, 0)} CHF`}
             xLabel={label}
             xTicks={(w) => spreadTicks(n, w, label, 64)}
             ariaLabel="Démonstration : patrimoine mesuré puis projeté, chiffres inventés" />
    </div>
  );
}

/* ----------------------------------------------------- 6. a correction */

const ROWS = [
  { date: "03.05", amount: "4.80" },
  { date: "12.05", amount: "5.20" },
  { date: "21.05", amount: "4.80", picked: true },
  { date: "prochain", amount: "…", future: true },
];

function CorrectionDemo() {
  const [scope, setScope] = useState<"none" | "pin" | "rule">("none");
  const changed = (r: (typeof ROWS)[number]) => scope === "rule" || (scope === "pin" && r.picked);
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      <div>
        <Try>Choisis la portée de la correction</Try>
        <Segmented<"none" | "pin" | "rule"> label="Portée de la correction" value={scope} onChange={setScope}
                   options={[{ id: "none", label: "Avant" }, { id: "pin", label: "Cette ligne" }, { id: "rule", label: "Tout ce bénéficiaire" }]} />
        <ul className="mt-3 divide-y divide-hairline rounded-2xl border border-hairline bg-surface">
          {ROWS.map((r) => (
            <li key={r.date} className={cx("flex items-center gap-3 px-3.5 py-2.5 text-[13.5px]", r.future && "text-muted")}>
              <span className="w-16 shrink-0 text-[12.5px] text-muted">{r.date}</span>
              <span className={cx("min-w-0 flex-1 truncate", r.picked && "font-medium text-ink")}>Café de la Gare{r.picked && " ←"}</span>
              <motion.span layout className="inline-flex items-center gap-1.5 text-[12.5px]">
                <motion.span animate={{ scale: changed(r) ? [1, 1.5, 1] : 1 }} transition={{ duration: 0.35 }}>
                  <Dot color={changed(r) ? "var(--s1)" : "var(--s2)"} />
                </motion.span>
                {changed(r) ? "Restaurants" : "Alimentation"}
              </motion.span>
              <span className="w-12 text-right num text-ink-2">{r.amount}</span>
            </li>
          ))}
        </ul>
      </div>
      <Prose>
        <p>Clique une transaction : sa fiche s'ouvre, avec « Reclasser » et deux portées :</p>
        <p><b>Cette ligne</b> : une épingle sur ce seul mouvement. Elle gagne toujours, même contre une règle. Elle survit à la réimportation du relevé.</p>
        <p><b>Tout ce bénéficiaire</b> : une règle qui reclasse ses mouvements passés <i>et futurs</i>. C'est elle qui rend la correction permanente.</p>
        <p>Chaque correction s'annule depuis le message qui la confirme, en bas de l'écran. Les corrections vivent à part du relevé, dans <code>data/overrides.json</code> : ce que la banque a imprimé n'est jamais réécrit.</p>
      </Prose>
    </div>
  );
}

/* ---------------------------------------------------------- the pages */

const PAGES: Record<string, { answers: string; more: string }> = {
  "/": { answers: "Où est passé l'argent sur la période ?", more: "Dépense, revenus et épargne, la répartition par catégorie ou par besoin / envie / épargne, le calendrier jour par jour, et la revue du mois : ce qui a changé par rapport à d'habitude." },
  "/transactions": { answers: "Quel mouvement, exactement ?", more: "Chaque ligne, filtrable par catégorie, compte, montant, recherche. Un clic ouvre sa fiche (reclasser, l'ajouter à un projet). Le filtre se reclasse en masse et s'exporte en CSV ou xlsx." },
  "/epargne": { answers: "Combien j'ai, et d'où ça vient ?", more: "Chaque poche (IBKR, 3a, crypto, titres hors relevé, cash) : valeur, ce que tu as versé contre ce que le marché a rendu, TWR ou MWR, repères, frais, risque. « Rafraîchir » relit IBKR, les indices et la crypto." },
  "/a-venir": { answers: "Qu'est-ce qui va tomber ?", more: "Les engagements lus dans tes paiements (rythme et montant réguliers), leurs prochaines dates, leurs hausses de prix, les délais pour les résilier, et ta franchise LAMal rejouée." },
  "/analyse": { answers: "Comment je dépense, d'habitude ?", more: "Le mois type en médianes, un an contre l'autre par catégorie, la régularité, le rythme du mois et de la semaine, ton inflation personnelle et la comparaison au ménage suisse." },
  "/previsions": { answers: "Où j'en serai ?", more: "Ton plan (ponctuels, versements programmés, mois de l'année), le cash projeté mois par mois et son seuil d'alerte (rappelé partout et dans le résumé de la semaine), prévu contre réel une fois les mois passés, le patrimoine projeté par poche avec sa bande d'incertitude, des scénarios à comparer (et à lisser : des virements IBKR en à-coups changés en ordre permanent au même point bas de cash), l'indépendance financière." },
  "/projets": { answers: "Combien m'a coûté ce voyage ?", more: "Des mouvements rassemblés sous un nom, au coût net (dépensé moins remboursé). Les séjours à l'étranger sont proposés tout seuls." },
  "/impots": { answers: "Qu'est-ce que je peux déduire ?", more: "Chaque rubrique de la déclaration que le relevé renseigne (3a, primes, frais de maladie, dons, transports, formation), la fortune au 31.12, les titres et biens hors relevé, les impôts encore dus estimés au taux déjà payé (et, si tu paies par acomptes mensuels, le solde probable du décompte), l'export." },
  "/bilan": { answers: "Comment s'est passée l'année ?", more: "Une douzaine de constats : le mois le plus cher et pourquoi, les habitudes, les pays, la plus longue pause." },
  "/corrections": { answers: "Qu'est-ce qui est mal classé ?", more: "La part de la dépense classée, les fusions proposées (une enseigne imprimée de plusieurs façons), tes règles personnelles, et le tri des Twint un par un." },
  "/assistant": { answers: "Et si je demandais en français ?", more: "Le modèle (Claude, DeepSeek ou Ollama) et ce qu'il coûte. Il met en mots des chiffres calculés par l'app, ne voit pas les noms, et rien ne s'écrit sans ton clic." },
  "/caviarder": { answers: "Envoyer un relevé sans s'exposer ?", more: "IBAN, noms et adresses retirés du PDF lui-même, relu après coup. L'original ne fait que passer." },
  "/importer": { answers: "Ajouter un relevé ?", more: "Dépose un PDF ou un CSV. Plus simple : télécharge-le sur le PC, l'app le ramasse dans la minute dans le dossier Téléchargements." },
  "/aide": { answers: "Comment ça marche ?", more: "Cette page." },
};

function PagesGrid({ flash }: { flash: string | null }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {[...NAV, UPLOAD].filter((n) => n.to !== "/aide").map((n) => {
        const p = PAGES[n.to];
        const id = helpAnchor(n.to);
        return (
          <motion.div key={n.to} id={id} className="scroll-mt-28"
                      animate={flash === id ? { boxShadow: ["0 0 0 0px var(--s0)", "0 0 0 3px var(--s0)", "0 0 0 0px var(--s0)"] } : {}}
                      transition={{ duration: 1.6 }} style={{ borderRadius: 16 }}>
            <Card className="h-full p-4">
              <div className="mb-1.5 flex items-center gap-2">
                <n.icon size={16} className="text-ink-2" />
                <Link to={n.to} className="text-[14.5px] font-semibold text-ink">{n.label}</Link>
              </div>
              <p className="text-[13.5px] font-medium text-ink">{p?.answers}</p>
              <p className="mt-1 text-[12.5px] leading-snug text-muted">{p?.more}</p>
            </Card>
          </motion.div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------- the keys */

const KEYS: [ReactNode, string][] = [
  [<><Kbd>Ctrl</Kbd> <Kbd>K</Kbd> ou <Kbd>/</Kbd></>, "Chercher : une page, une période, une catégorie, un bénéficiaire, un montant, ou poser une question"],
  [<><Kbd>←</Kbd> <Kbd>→</Kbd></>, "Période précédente, suivante (de la même durée)"],
  [<Kbd>Échap</Kbd>, "Remonter d'un niveau : du jour au mois, du mois à l'année"],
  [<Kbd>[</Kbd>, "Replier ou déplier la barre latérale"],
  [<Kbd>?</Kbd>, "Ouvrir cette page, sur ce qui concerne la page où tu es"],
  [<><Kbd>←</Kbd> <Kbd>→</Kbd> <Kbd>Entrée</Kbd></>, "Sur un graphique qui a le focus : lire colonne par colonne, ouvrir"],
  [<><Kbd>1</Kbd>…<Kbd>9</Kbd> <Kbd>S</Kbd> <Kbd>Z</Kbd></>, "Tri des Twint : choisir la catégorie, passer, annuler le dernier"],
];

/* ---------------------------------------------------------------- FAQ */

const FAQ: [string, ReactNode][] = [
  ["Le tableau de bord signale une rupture de solde", <>Une ligne du relevé a été mal lue ou manque. Le bouton ⟳ en haut, ou relancer <code>.\run.bat</code>, relit les imports ; si elle reste, <code>.\run.bat --reparse</code> relit aussi les relevés déjà importés.</>],
  ["Épargne affiche « Données en retard »", <>Une poche n'a pas de point depuis plus de 7 jours. « Rafraîchir » sur la page Épargne relit IBKR, les indices du 3a et la crypto ; <code>run.bat</code> le fait aussi une fois par jour.</>],
  ["Des centaines de Twint « non identifiés »", <>Un Twint envoyé n'imprime que « Paiement Twint » : ni bénéficiaire ni lieu. Seul toi peux les classer : Corrections › Trier les Twint, une touche par Twint, avec des suggestions apprises de tes choix passés.</>],
  ["Un panneau a disparu", <>Un panneau qui ne peut rien dire est absent : pas de saisonnalité sur trois semaines, pas de comparaison annuelle sur une seule année. Élargis la période.</>],
  ["La part « non dépensée » ne s'ouvre pas", <>Elle est dessinée creuse parce qu'aucune transaction n'est derrière : c'est ce qui reste du revenu, pas un virement.</>],
  ["Partager une vue", <>L'adresse dit tout : période, unité, filtres, bascules. Copie-la : elle rouvre exactement la même vue, et le bouton retour du navigateur marche.</>],
  ["Mettre l'app à jour", <>Le bouton « Mettre à jour » dans la barre latérale récupère la dernière version et redémarre. Si une dépendance a changé, il demande de relancer <code>.\run.bat</code>.</>],
  ["Sur le téléphone", <>L'app se lit par Tailscale (jamais exposée sur internet). Un premier toucher sur un graphique lit la colonne, un second l'ouvre ; les fenêtres se ferment en les glissant vers le bas.</>],
  ["Mes données sont-elles envoyées quelque part ?", <>Non : relevés, ledger et corrections restent dans <code>inbox/</code> et <code>data/</code> sur ce PC. La sauvegarde est un zip chiffré (garde la clé <code>data/backup.key</code> dans ton gestionnaire de mots de passe). L'assistant, si tu l'utilises, ne reçoit que des chiffres et des catégories, noms masqués.</>],
];

/* ---------------------------------------------------------------- page */

export default function HelpPage() {
  const location = useLocation();
  const [flash, setFlash] = useState<string | null>(null);

  // /aide#p-epargne: the card of that page, brought into view and flashed;
  // /aide#graphiques: a section, unfolded and reached like the contents do.
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    const t = window.setTimeout(() => {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.hasAttribute("data-section")) goToSection(id);
      else {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        setFlash(id);
      }
    }, 120);
    return () => window.clearTimeout(t);
  }, [location.hash]);

  return (
    <div>
      <PageHeader title="Manuel" subtitle="Ce que chaque page répond, et comment s'y déplacer. Les graphiques de cette page sont les vrais, sur des chiffres inventés : essaie-les." />
      <div className="space-y-4 sm:space-y-5">
        <Panel id="principe" title="Le principe" hint="D'un relevé à un chiffre">
          <Flow />
          <Prose>
            <p className="mt-4">Tout part de tes relevés. L'app n'a ni compte ni connexion à une banque : elle lit les fichiers que tu télécharges, et rien ne quitte ce PC.</p>
          </Prose>
        </Panel>

        <Panel id="pages" title="Les pages" hint="La question à laquelle chacune répond">
          <PagesGrid flash={flash} />
        </Panel>

        <Panel id="periode" title="La période" hint="Une fenêtre de temps et une unité : toute la navigation">
          <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
            <PeriodDemo />
            <Prose>
              <p>En haut de l'écran, le titre de la période (« Mai 2025 ») s'ouvre sur les préréglages et l'<b>unité</b> des colonnes : jour, semaine, mois, trimestre, semestre, année. « Auto » choisit la plus lisible.</p>
              <p>Les flèches avancent d'une période de la même durée. <b>Échap</b> remonte d'un niveau, le fil d'ariane aussi.</p>
              <p>La période te suit d'une page à l'autre : passer de Tableau de bord à Transactions garde « Mai 2025 ». Et l'adresse la contient : un favori rouvre exactement la même vue.</p>
            </Prose>
          </div>
        </Panel>

        <Panel id="graphiques" title="Lire un graphique" hint="Survoler, cliquer, glisser">
          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <ColumnsDemo />
            <Prose>
              <p><b>Survoler</b> une colonne en donne le détail. <b>Cliquer</b> l'ouvre : un mois descend au jour, et l'infobulle dit d'avance où le clic mène.</p>
              <p><b>Glisser</b> sur plusieurs colonnes ouvre la fenêtre qu'elles couvrent : de juin à septembre, d'un seul geste.</p>
              <p><b>Médiane</b> trace le mois typique, calculée seulement sur les périodes complètes : un mois entamé ne la tire pas vers le bas.</p>
              <p>Au doigt : un premier toucher lit, un second ouvre. Au clavier : <Kbd>Tab</Kbd> jusqu'au graphique, puis <Kbd>←</Kbd> <Kbd>→</Kbd> et <Kbd>Entrée</Kbd>.</p>
            </Prose>
          </div>
        </Panel>

        <Panel id="calendrier" title="Le calendrier" hint="La dépense jour par jour">
          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <CalendarDemo />
            <Prose>
              <p><b>Plus c'est foncé, plus tu as dépensé</b> ce jour-là, dans les deux thèmes. Un jour <b>sans dépense</b> n'a qu'un contour : jamais une case grise, qui se lirait comme la plus chargée.</p>
              <p>Les paliers sont des quantiles de la période : la case la plus foncée est un jour parmi les plus chers de cette fenêtre, pas un montant fixe.</p>
            </Prose>
          </div>
        </Panel>

        <Panel id="courbes" title="Les courbes de patrimoine" hint="Mesuré, puis projeté">
          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <LinesDemo />
            <Prose>
              <p>Le trait vertical, c'est <b>aujourd'hui</b>. À gauche, la valeur mesurée (relevés, courtier, 3a). À droite, la projection : le plan de Prévisions et le rendement que <b>tu</b> as déclaré, jamais un rendement inventé.</p>
              <p>La <b>bande</b> autour de la projection vient de la volatilité déclarée : elle s'élargit avec le temps, parce que l'incertitude s'accumule.</p>
              <p>Une courbe s'arrête là où les données s'arrêtent : un trou n'est jamais rempli par un zéro.</p>
            </Prose>
          </div>
        </Panel>

        <Panel id="corriger" title="Corriger une catégorie" hint="Une ligne, ou tout un bénéficiaire">
          <CorrectionDemo />
        </Panel>

        <Panel id="raccourcis" title="Raccourcis clavier" hint="Au bureau">
          <ul className="divide-y divide-hairline">
            {KEYS.map(([k, what], i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-[13.5px]">
                <span className="w-44 shrink-0">{k}</span>
                <span className="min-w-0 flex-1 text-ink-2">{what}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel id="questions" title="Questions fréquentes">
          <div className="space-y-1">
            {FAQ.map(([q, a]) => (
              <Reveal key={q} summary={q}>
                <p className="max-w-[75ch] pb-2 pl-5 text-[13.5px] leading-relaxed text-ink-2">{a}</p>
              </Reveal>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
