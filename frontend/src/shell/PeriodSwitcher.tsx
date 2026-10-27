/** The window: where it is, the one before and after, and every way to pick
 * another. Always at hand -- in the sticky bar -- because every figure of the
 * page answers "over which period?". */
import { CalendarRange, ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";
import { Popover } from "radix-ui";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Sheet } from "@/components/Sheet";
import { Button, Segmented, cx } from "@/components/ui";
import { useApi, prefetch } from "@/lib/api";
import { MONTHS_SHORT, frDate } from "@/lib/format";
import { useDesktop, useHotkeys } from "@/lib/hooks";
import type { Period } from "@/lib/types";
import { nextParams, useView, withQuery, type Patch } from "@/lib/url";

/** Every current key rides along except the page number: a new window
 * starts on its first page. */
function useWindowNav() {
  const view = useView();
  const keep = useMemo(
    () => [...new Set([...view.params.keys()])].filter((k) => k !== "page"),
    [view.params],
  );
  const to = (patch: Patch) => withQuery(view.pathname, nextParams(view.params, patch, keep));
  return { ...view, to };
}

export function usePeriod() {
  const { query } = useView();
  return useApi<Period>("/api/period", query);
}

export function PeriodSwitcher({ compact = false }: { compact?: boolean }) {
  const { data: period } = usePeriod();
  const nav = useWindowNav();
  const desktop = useDesktop();
  const [open, setOpen] = useState(false);

  const n = period?.neighbours;
  const prevHref = n?.prev.available
    ? nav.to({ from: n.prev.start, to: n.prev.end, grain: period?.grain })
    : null;
  const nextHref = n?.next.available
    ? nav.to({ from: n.next.start, to: n.next.end, grain: period?.grain })
    : null;
  const parent = period && period.crumbs.length > 1 ? period.crumbs[period.crumbs.length - 2] : null;

  useHotkeys({
    arrowleft: () => prevHref && nav.navigate(prevHref, { preventScrollReset: true }),
    arrowright: () => nextHref && nav.navigate(nextHref, { preventScrollReset: true }),
    escape: () => parent && nav.navigate(nav.to({ from: parent.start, to: parent.end, grain: "auto" }), { preventScrollReset: true }),
  });

  const trigger = (
    <button
      type="button"
      className={cx(
        "group flex min-w-0 items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-left transition hover:bg-surface-2",
        compact ? "max-w-[56vw]" : "",
      )}
      aria-label="Changer la période"
    >
      <CalendarRange size={16} className="shrink-0 text-muted" />
      <span className={cx("truncate font-semibold tracking-tight", compact ? "text-[15px]" : "text-[15px]")}>
        {period?.title ?? "…"}
      </span>
      <ChevronDown size={15} className="shrink-0 text-muted transition group-data-[state=open]:rotate-180" />
    </button>
  );

  const arrow = (href: string | null, dir: "prev" | "next", label?: string) => {
    const Icon = dir === "prev" ? ChevronLeft : ChevronRight;
    const cls = "grid size-9 shrink-0 place-items-center rounded-xl text-ink-2 transition hover:bg-surface-2 hover:text-ink";
    return href ? (
      <Link
        to={href}
        preventScrollReset
        className={cls}
        aria-label={dir === "prev" ? `Période précédente : ${label}` : `Période suivante : ${label}`}
        title={label}
        onMouseEnter={() => prefetchFor(href)}
      >
        <Icon size={18} />
      </Link>
    ) : (
      <span className={cx(cls, "opacity-30")} aria-hidden><Icon size={18} /></span>
    );
  };

  const picker = period && <PeriodPicker period={period} onDone={() => setOpen(false)} />;

  return (
    <div className="flex min-w-0 items-center gap-0.5">
      {arrow(prevHref, "prev", n?.prev_label)}
      {desktop ? (
        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger asChild>{trigger}</Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              sideOffset={8}
              align="start"
              collisionPadding={16}
              className="z-50 w-[420px] rounded-[20px] border border-hairline bg-surface p-4 shadow-pop outline-none data-[state=open]:animate-[float-in_.16s_ease-out]"
            >
              {picker}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      ) : (
        <>
          <span onClick={() => setOpen(true)} className="min-w-0">{trigger}</span>
          <Sheet open={open} onOpenChange={setOpen} title="Période"
                 description={period ? `${frDate(period.start)} → ${frDate(period.end)} · ${period.days} jours` : undefined}>
            {picker}
          </Sheet>
        </>
      )}
      {arrow(nextHref, "next", n?.next_label)}
    </div>
  );
}

/** Warm the cache for a window the reader is about to open. */
function prefetchFor(href: string) {
  const [path, query = ""] = href.split("?");
  const endpoint = path === "/" || path === "" ? "/api/dashboard"
    : path.startsWith("/transactions") ? "/api/transactions"
    : path.startsWith("/epargne") ? "/api/savings" : null;
  if (endpoint) prefetch(endpoint, query);
  prefetch("/api/period", query);
}

function PeriodPicker({ period, onDone }: { period: Period; onDone: () => void }) {
  const nav = useWindowNav();
  const go = (patch: Patch) => {
    nav.navigate(nav.to(patch), { preventScrollReset: true });
    onDone();
  };
  const [from, setFrom] = useState(period.start);
  const [to, setTo] = useState(period.end);
  const low = period.bounds.low;
  const high = period.bounds.high;
  const [year, setYear] = useState(Number(period.end.slice(0, 4)));
  const lowYear = Number(low.slice(0, 4));
  const highYear = Number(high.slice(0, 4));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    go({ from, to, grain: period.auto_grain ? "auto" : period.grain });
  };

  const monthWindow = (m: number) => {
    const first = `${year}-${String(m + 1).padStart(2, "0")}-01`;
    const last = new Date(year, m + 1, 0);
    const end = `${year}-${String(m + 1).padStart(2, "0")}-${String(last.getDate()).padStart(2, "0")}`;
    return { first, end };
  };

  return (
    <div className="space-y-5">
      {period.crumbs.length > 1 && (
        <nav aria-label="Fil d'ariane" className="flex flex-wrap items-center gap-1 text-[13px]">
          {period.crumbs.map((c, i) => (
            <span key={c.label + i} className="flex items-center gap-1">
              {i > 0 && <span className="text-muted" aria-hidden>›</span>}
              {c.current ? (
                <span className="rounded-lg bg-surface-2 px-2 py-1 font-semibold">{c.label}</span>
              ) : (
                <button type="button" className="rounded-lg px-2 py-1 text-ink-2 hover:bg-surface-2 hover:text-ink"
                        onClick={() => go({ from: c.start, to: c.end, grain: "auto" })}>
                  {c.label}
                </button>
              )}
            </span>
          ))}
        </nav>
      )}

      {period.preset_groups.map((g) => (
        <div key={g.name}>
          <div className="eyebrow mb-2">{g.name}</div>
          <div className="flex flex-wrap gap-1.5">
            {g.buttons.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => go({ preset: p.id, from: null, to: null, grain: "auto" })}
                className={cx(
                  "rounded-xl border px-3 py-2 text-[13.5px] font-medium transition",
                  p.active
                    ? "border-transparent bg-ink text-page"
                    : "border-hairline-2 bg-surface hover:bg-surface-2",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      ))}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="eyebrow">Un mois</span>
          <span className="flex items-center gap-1">
            <button type="button" className="grid size-7 place-items-center rounded-lg hover:bg-surface-2 disabled:opacity-30"
                    disabled={year <= lowYear} onClick={() => setYear(year - 1)} aria-label="Année précédente">
              <ChevronLeft size={15} />
            </button>
            <span className="num w-12 text-center text-[13.5px] font-semibold">{year}</span>
            <button type="button" className="grid size-7 place-items-center rounded-lg hover:bg-surface-2 disabled:opacity-30"
                    disabled={year >= highYear} onClick={() => setYear(year + 1)} aria-label="Année suivante">
              <ChevronRight size={15} />
            </button>
          </span>
        </div>
        <div className="grid grid-cols-6 gap-1.5">
          {MONTHS_SHORT.map((label, m) => {
            const { first, end } = monthWindow(m);
            const outside = end < low || first > high;
            const active = period.start === first && (period.end === end || (period.end === high && high < end));
            return (
              <button
                key={label}
                type="button"
                disabled={outside}
                onClick={() => go({ from: first < low ? low : first, to: end > high ? high : end, grain: "auto" })}
                className={cx(
                  "rounded-lg py-2 text-[12.5px] font-medium capitalize transition disabled:opacity-25",
                  active ? "bg-ink text-page" : "bg-surface-2 hover:bg-surface-3",
                )}
              >
                {label.replace(".", "")}
              </button>
            );
          })}
        </div>
      </div>

      <form onSubmit={submit}>
        <div className="eyebrow mb-2">Dates précises</div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-[130px] flex-1 flex-col gap-1 text-[12px] text-muted">
            Du
            <input type="date" value={from} min={low} max={high} onChange={(e) => setFrom(e.target.value)}
                   className="h-10 rounded-xl border border-hairline-2 bg-surface px-3 text-[16px] text-ink sm:text-[14px]" />
          </label>
          <label className="flex min-w-[130px] flex-1 flex-col gap-1 text-[12px] text-muted">
            Au
            <input type="date" value={to} min={low} max={high} onChange={(e) => setTo(e.target.value)}
                   className="h-10 rounded-xl border border-hairline-2 bg-surface px-3 text-[16px] text-ink sm:text-[14px]" />
          </label>
          <Button type="submit" variant="primary">Appliquer</Button>
        </div>
      </form>

      <div>
        <div className="eyebrow mb-2">Granularité</div>
        <Segmented
          label="Granularité"
          columns={4}
          value={period.auto_grain ? "auto" : period.grain}
          options={[{ id: "auto", label: "Auto" }, ...period.grains.map((g) => ({ id: g.id, label: g.label }))]}
          onChange={(id) => go({ from: period.start, to: period.end, grain: id })}
        />
      </div>
    </div>
  );
}
