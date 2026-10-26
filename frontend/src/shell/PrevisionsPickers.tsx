/** The forecast's two choices, beside its title in the sticky bar: how far
 * ahead, and which plan -- both scope every figure of the page, as the
 * period does elsewhere. */
import { CalendarRange, Check, ChevronDown, Layers, Plus, TrendingUp } from "lucide-react";
import { Popover } from "radix-ui";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { cx } from "@/components/ui";
import { NEW_SCENARIO_EVENT, PREVISIONS_KEEP, openSection, planAction, usePrevisions } from "@/lib/previsions";
import { useView } from "@/lib/url";

function Picker({ icon, label, value, compact, children, open, setOpen, width = "w-56" }: {
  icon: ReactNode; label: string; value: ReactNode; compact: boolean; children: ReactNode;
  open: boolean; setOpen: (o: boolean) => void; width?: string;
}) {
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" aria-label={label}
                className="flex min-w-0 shrink items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[14px] font-semibold transition hover:bg-surface-2">
          {!compact && <span className="shrink-0 text-muted">{icon}</span>}
          <span className="truncate">{value}</span>
          <ChevronDown size={15} className="shrink-0 text-muted" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} align="start"
                         className={cx("z-50 max-h-[70vh] overflow-y-auto rounded-2xl border border-hairline bg-surface p-1.5 shadow-pop", width)}>
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

const row = (on: boolean) => cx("flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[14px] no-underline transition",
  on ? "bg-surface-2 font-semibold text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink");

export function HorizonPicker({ compact = false }: { compact?: boolean }) {
  const { data } = usePrevisions();
  const { href } = useView();
  const [open, setOpen] = useState(false);
  if (!data || data.empty) return null;
  const options = data.horizons.some((h) => h.id === data.months)
    ? data.horizons : [...data.horizons, { id: data.months, label: data.horizon_label }];
  return (
    <Picker icon={<CalendarRange size={16} />} label={`Horizon : ${data.horizon_label}`} compact={compact}
            value={data.horizon_label} open={open} setOpen={setOpen} width="w-44">
      {options.map((h) => {
        const on = h.id === data.months;
        return (
          <Link key={h.id} to={href({ months: h.id === 12 ? null : h.id }, { keep: PREVISIONS_KEEP })} preventScrollReset
                onClick={() => setOpen(false)} aria-current={on ? "true" : undefined} className={cx(row(on), "justify-between")}>
            {h.label}{on && <Check size={15} />}
          </Link>
        );
      })}
    </Picker>
  );
}

export function ScenarioPicker({ compact = false }: { compact?: boolean }) {
  const { data } = usePrevisions();
  const [open, setOpen] = useState(false);
  if (!data || data.empty) return null;
  const plans = data.comparison;
  const shown = plans.find((p) => p.active) ?? plans[0];
  const name = shown?.name ?? "Plan sans nom";
  const pick = async (target: string) => {
    setOpen(false);
    const r = await planAction(data.months, { action: "plan-switch", name: target });
    if (r.errors) toast.error("Ce scénario n'existe plus");
    else toast.success(`« ${target} » affiché`);
  };
  return (
    <Picker icon={<Layers size={16} />} label={`Scénario affiché : ${name}`} compact={compact}
            value={<span className={cx(!shown?.name && "italic font-medium")}>{name}</span>} open={open} setOpen={setOpen} width="w-64">
      {plans.map((p) => {
        const on = !!p.active;
        return (
          <button key={p.name ?? "_"} type="button" disabled={on || !p.name} aria-current={on ? "true" : undefined}
                  onClick={() => p.name && void pick(p.name)} className={row(on)}>
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: p.slot != null ? `var(--s${p.slot})` : "var(--unsorted)" }} />
            <span className={cx("min-w-0 flex-1 truncate", !p.name && "italic")}>{p.name ?? "Plan sans nom"}</span>
            {on && <Check size={15} />}
          </button>
        );
      })}
      <div className="my-1 h-px bg-hairline" />
      <button type="button" className={row(false)}
              onClick={() => { setOpen(false); window.dispatchEvent(new Event(NEW_SCENARIO_EVENT)); }}>
        <Plus size={15} className="text-muted" />Nouveau scénario…
      </button>
    </Picker>
  );
}

const QUICK_RATES = [null, 2, 4, 6] as const;
const QUICK_VOLS = [0, 10, 15, 20] as const;
const pct = (r: number) => `${(r * 100).toFixed(1).replace(/\.0$/, "")} %`;

/** The assumed return and volatility, said in a few characters and
 * changed in one click: constant rates, the market scenarios, a band width.
 * The detail stays in its panel, one click away. */
export function RatePicker({ compact = false }: { compact?: boolean }) {
  const { data } = usePrevisions();
  const [open, setOpen] = useState(false);
  if (!data || data.empty) return null;
  const segs = data.plan.rate_segments;
  const vol = data.plan.vol;
  const measured = data.wealth?.vol_measured ?? null;
  const rate = !segs.length ? "aucun rendement" : segs.length === 1 ? `${pct(segs[0][1])} / an`
    : `${pct(segs[0][1])} → ${pct(segs[segs.length - 1][1])}`;
  const same = (a: [number, number][], b: { months: number; rate: number }[]) =>
    a.length === b.length && a.every(([m, r], i) => m === b[i].months && Math.abs(r - b[i].rate) < 1e-9);
  const run = async (body: Record<string, unknown>, done: string) => {
    setOpen(false);
    const r = await planAction(data.months, body);
    if (r.errors) toast.error("Non appliqué", { description: Object.values(r.errors)[0] });
    else toast.success(done);
  };
  const constant = (r: number | null) => run(
    { action: "rate", months: [r == null ? "" : "12"], rates: [r == null ? "" : String(r)] },
    r == null ? "Aucun rendement supposé" : `${r} % par an, constant`);
  const pill = (on: boolean) => cx("rounded-full border px-2.5 py-1 text-[12.5px] transition",
    on ? "border-ink bg-surface-2 font-semibold text-ink" : "border-hairline-2 text-ink-2 hover:bg-surface-2");
  return (
    <Picker icon={<TrendingUp size={16} />} label={`Rendement supposé : ${rate}`} compact={compact} width="w-[min(22rem,calc(100vw-24px))]"
            value={<>{compact && segs.length > 1 ? `${pct(segs[0][1])}…` : rate}
              {!compact && <span className="ml-1.5 font-normal text-muted">· vol {vol != null ? pct(vol) : measured != null ? `${pct(measured)} mes.` : "mesurée"}</span>}</>}
            open={open} setOpen={setOpen}>
      <div className="space-y-3 p-1.5">
        <div>
          <div className="eyebrow mb-1.5">Rendement, par an</div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_RATES.map((r) => {
              const on = r == null ? !segs.length : segs.length === 1 && Math.abs(segs[0][1] - r / 100) < 1e-9;
              return <button key={String(r)} type="button" className={pill(on)} onClick={() => void constant(r)}>{r == null ? "Aucun" : `${r} %`}</button>;
            })}
          </div>
        </div>
        <div>
          <div className="eyebrow mb-1">Scénarios de marché</div>
          <div className="max-h-56 space-y-0.5 overflow-y-auto">
            {[...data.builtin_scenarios.map((s) => ({ id: `builtin:${s.key}`, name: s.label, note: s.note, segments: s.segments, months: s.months })),
              ...data.plan.scenarios.map((s) => ({ id: `saved:${s.name}`, name: s.name, note: "à toi", segments: s.segments, months: s.months }))].map((s) => {
              const on = same(segs, s.segments);
              return (
                <button key={s.id} type="button" onClick={() => void run({ action: "scenario-apply", scenario: s.id }, `« ${s.name} » appliqué`)}
                        className={cx("flex w-full items-start gap-2 rounded-xl px-2.5 py-1.5 text-left transition", on ? "bg-surface-2" : "hover:bg-surface-2")}>
                  <span className="min-w-0 flex-1">
                    <span className={cx("block truncate text-[13.5px]", on ? "font-semibold" : "text-ink")}>{s.name}</span>
                    <span className="block truncate text-[11.5px] text-muted">{s.note}</span>
                  </span>
                  {s.months && <span className="shrink-0 pt-0.5 text-[11px] text-muted">{s.months % 12 === 0 ? `${s.months / 12} ans` : `${s.months} mois`}</span>}
                  {on && <Check size={15} className="mt-0.5 shrink-0" />}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <div className="eyebrow mb-1.5">Volatilité, la largeur de la zone</div>
          <div className="flex flex-wrap gap-1.5">
            <button type="button" className={pill(vol == null)} onClick={() => void run({ action: "vol", amount: "" }, "Volatilité mesurée")}>
              Mesurée{measured != null ? ` · ${pct(measured)}` : ""}
            </button>
            {QUICK_VOLS.map((v) => (
              <button key={v} type="button" className={pill(vol != null && Math.abs(vol - v / 100) < 1e-9)}
                      onClick={() => void run({ action: "vol", amount: String(v) }, `Volatilité ${v} %`)}>{v} %</button>
            ))}
          </div>
        </div>
        <button type="button" onClick={() => { setOpen(false); openSection("p-rates"); }}
                className="flex w-full items-center justify-between rounded-xl border-t border-hairline px-2.5 pt-2.5 text-[13px] text-ink-2 hover:text-ink">
          Barème par périodes, décrire en mots…<ChevronDown size={14} className="-rotate-90" />
        </button>
      </div>
    </Picker>
  );
}
