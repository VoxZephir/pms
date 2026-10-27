/** The frame around every page: a sidebar on the laptop; on the phone a
 * glass top bar with the period and a tab bar where the thumb is. */
import { ChevronDown, Ellipsis, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, Search, Sun, Wand2 } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { Toaster, toast } from "sonner";

import { Sheet } from "@/components/Sheet";
import { IconButton, cx } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { useDesktop, useHotkeys, useStored } from "@/lib/hooks";
import { resolvedTheme, useTheme } from "@/lib/theme";
import type { Meta } from "@/lib/types";
import { useView } from "@/lib/url";

import { CommandPalette } from "./CommandPalette";
import { NAV, TABS, UPLOAD, isActive } from "./nav";
import { PeriodSwitcher } from "./PeriodSwitcher";
import { PocketPicker } from "./PocketPicker";
import { HorizonPicker, RatePicker, ScenarioPicker } from "./PrevisionsPickers";
import { ScrollDock, SectionList, type Section, useSections } from "./Sections";
import { UpdateNotice } from "./Update";

export function AppShell() {
  const desktop = useDesktop();
  const location = useLocation();
  const [palette, setPalette] = useState(false);
  const theme = useTheme();
  const { sections, active, scrolled } = useSections();
  // The sidebar folded to a rail of icons: more room for the page. Kept per
  // browser, like the "Plus" group.
  const [folded, setFolded] = useStored<boolean>("pms-sidebar-folded", false);
  const page = NAV.find((n) => isActive(n.to, location.pathname));
  // Pages outside the navigation name themselves in the bar.
  const title = location.pathname.startsWith("/corrections/tri") ? "Trier les Twint"
    : location.pathname.startsWith("/importer") ? UPLOAD.label
    : location.pathname.startsWith("/jour/") ? "Journée"
    : page?.short ?? page?.label ?? "";

  useHotkeys({
    "mod+k": (e) => { e.preventDefault(); setPalette(true); },
    "/": (e) => { e.preventDefault(); setPalette(true); },
    "[": () => { if (desktop) setFolded(!folded); },
  });

  // A new page starts at its top; a new window of the same page keeps the
  // reader where they were (links say preventScrollReset).
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-xl focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop">
        Aller au contenu
      </a>
      {desktop && <Sidebar onSearch={() => setPalette(true)} theme={theme} sections={sections} active={active}
                           folded={folded} onFold={() => setFolded(!folded)} />}
      <div className={cx(desktop && (folded ? "pl-[64px]" : "pl-[248px]"), "transition-[padding] duration-200")}>
        <TopBar desktop={desktop} periodPage={!!page?.period && !location.pathname.startsWith("/jour/")} title={title}
                onSearch={() => setPalette(true)} />
        <main id="main" className={cx(
          "mx-auto w-full max-w-[1280px] px-4 pt-4 sm:px-6 lg:px-10 lg:pt-6",
          desktop ? "pb-16" : "pb-[calc(96px+env(safe-area-inset-bottom))]",
        )}>
          <Outlet />
        </main>
      </div>
      {!desktop && <TabBar theme={theme} onSearch={() => setPalette(true)} />}
      <ScrollDock desktop={desktop} sections={sections} active={active} scrolled={scrolled} />
      <CommandPalette open={palette} onOpenChange={setPalette} theme={theme} />
      <Toaster
        position={desktop ? "bottom-right" : "top-center"}
        offset={desktop ? 24 : 12}
        toastOptions={{
          className: "!rounded-2xl !border !border-hairline !bg-surface !text-ink !shadow-pop",
        }}
      />
    </div>
  );
}

function Brand({ folded }: { folded?: boolean }) {
  return (
    <Link to="/" aria-label="PMS, tableau de bord" className={cx("flex items-center gap-2.5 rounded-xl py-1.5 no-underline", folded ? "px-1" : "px-2")}>
      <span className="grid size-8 place-items-center rounded-[10px] bg-ink text-[13px] font-bold tracking-tight text-page">P</span>
      {!folded && <span className="text-[15px] font-semibold tracking-tight">PMS</span>}
    </Link>
  );
}

function SideLink({ item, folded }: { item: (typeof NAV)[number]; folded?: boolean }) {
  const { pageHref } = useView();
  const location = useLocation();
  const active = isActive(item.to, location.pathname);
  return (
    <NavLink
      to={pageHref(item.to)}
      aria-current={active ? "page" : undefined}
      title={folded ? item.label : undefined}
      className={cx(
        "relative flex h-8 items-center gap-3 rounded-xl text-[13.5px] font-medium no-underline transition",
        folded ? "justify-center px-0" : "px-3",
        active ? "text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      {active && (
        <motion.span layoutId="side-active"
                     className="absolute inset-0 rounded-xl bg-surface shadow-[0_1px_2px_rgba(0,0,0,.06),0_0_0_1px_var(--hairline)]"
                     transition={{ type: "spring", stiffness: 500, damping: 40 }} />
      )}
      <item.icon size={16} className="relative" strokeWidth={1.9} />
      <span className={folded ? "sr-only" : "relative"}>{item.label}</span>
    </NavLink>
  );
}

function Sidebar({ onSearch, theme, sections, active, folded, onFold }: {
  onSearch: () => void; theme: ReturnType<typeof useTheme>; sections: Section[]; active: string | null;
  folded: boolean; onFold: () => void;
}) {
  const location = useLocation();
  const { data: meta } = useApi<Meta>("/api/meta");
  const [moreStored, setMore] = useStored<boolean>("pms-nav-more", false);
  // A page of the folded group opens it: the current page is always in sight.
  const moreOpen = moreStored || NAV.some((n) => n.more && isActive(n.to, location.pathname));
  const fold = (
    <IconButton label={folded ? "Déplier la barre latérale ( [ )" : "Replier la barre latérale ( [ )"} onClick={onFold}>
      {folded ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
    </IconButton>
  );
  const shell = "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-hairline bg-[color-mix(in_srgb,var(--surface)_60%,var(--page))] py-4";
  if (folded) {
    // The rail: the same destinations as icons, named on hover; the page's
    // sections and the notices wait for the sidebar to open again -- a
    // notice is flagged by a dot on the unfold button.
    const flagged = !!meta && (meta.late.length > 0 || !!meta.backup);
    return (
      <aside className={cx(shell, "w-[64px] items-center px-2")}>
        <Brand folded />
        <div className="relative mt-3">
          {fold}
          {flagged && <i className="pointer-events-none absolute right-1 top-1 size-2 rounded-full bg-warn" aria-hidden />}
        </div>
        <IconButton label="Rechercher (Ctrl K)" onClick={onSearch}><Search size={16} /></IconButton>
        <nav aria-label="Navigation principale" className="no-scrollbar mt-3 flex min-h-0 w-full flex-1 flex-col gap-px overflow-y-auto">
          {NAV.filter((n) => !n.more).map((item) => <SideLink key={item.to} item={item} folded />)}
          <div className="mx-auto my-1.5 h-px w-6 bg-hairline-2" />
          {NAV.filter((n) => n.more).map((item) => <SideLink key={item.to} item={item} folded />)}
        </nav>
        <div className="flex flex-col items-center gap-1 pt-3">
          <NavLink to={UPLOAD.to} title={UPLOAD.label} aria-label={UPLOAD.label}
                   className={({ isActive: a }) => cx(
                     "grid size-8 place-items-center rounded-xl no-underline transition",
                     a ? "bg-surface text-ink shadow-[0_0_0_1px_var(--hairline)]" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                   )}>
            <UPLOAD.icon size={16} strokeWidth={1.9} />
          </NavLink>
          <IconButton label={resolvedTheme(theme.theme) === "dark" ? "Thème clair" : "Thème sombre"} onClick={theme.toggle}>
            {resolvedTheme(theme.theme) === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </IconButton>
          <RefreshButton compact />
        </div>
      </aside>
    );
  }
  return (
    <aside className={cx(shell, "w-[248px] px-3")}>
      <div className="flex items-center justify-between">
        <Brand />
        {fold}
      </div>
      <button
        type="button"
        onClick={onSearch}
        className="mt-4 flex h-9 items-center gap-2 rounded-xl border border-hairline-2 bg-surface px-3 text-[13px] text-muted shadow-[var(--shadow-sm)] transition hover:text-ink"
      >
        <Search size={15} />
        <span className="flex-1 text-left">Rechercher…</span>
        <kbd className="rounded-md border border-hairline-2 px-1.5 text-[11px]">Ctrl K</kbd>
      </button>
      <nav aria-label="Navigation principale" className="mt-4 flex flex-col gap-px">
        {NAV.filter((n) => !n.more).map((item) => <SideLink key={item.to} item={item} />)}
        <button type="button" onClick={() => setMore(!moreOpen)} aria-expanded={moreOpen}
                className="mt-1 flex h-7 items-center gap-2 rounded-lg px-3 text-[12px] font-medium text-muted hover:text-ink">
          <ChevronDown size={13} className={cx("transition-transform", !moreOpen && "-rotate-90")} />Plus
        </button>
        {moreOpen && NAV.filter((n) => n.more).map((item) => <SideLink key={item.to} item={item} />)}
      </nav>
      {sections.length > 1 && (
        <nav aria-label="Sur cette page" className="no-scrollbar mt-6 min-h-0 flex-1 overflow-y-auto px-1">
          <div className="eyebrow mb-1.5 px-2">Sur cette page</div>
          <SectionList sections={sections} active={active} />
        </nav>
      )}
      <div className="mt-auto flex flex-col gap-1 pt-3">
        {meta && meta.late.length > 0 && (
          <Link to="/importer" title="Relevé attendu"
                className="truncate rounded-lg border border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,transparent)] px-2.5 py-1 text-[12px] text-ink-2 no-underline">
            <b className="text-ink">Relevé attendu</b> · {meta.late.map((l) => `${l.bank} ${l.days} j`).join(", ")}
          </Link>
        )}
        <UpdateNotice compact />
        {meta?.backup && (
          <div role="status" title={meta.backup.detail}
               className="truncate rounded-lg border border-[color-mix(in_srgb,var(--critical)_30%,transparent)] bg-[color-mix(in_srgb,var(--critical)_7%,transparent)] px-2.5 py-1 text-[12px] text-ink-2">
            <b className="text-ink">{meta.backup.title}</b>
          </div>
        )}
        <div className="flex items-center gap-1">
          <NavLink to={UPLOAD.to}
                   className={({ isActive: a }) => cx(
                     "flex h-8 min-w-0 flex-1 items-center gap-2.5 rounded-xl px-3 text-[13.5px] font-medium no-underline transition",
                     a ? "bg-surface text-ink shadow-[0_0_0_1px_var(--hairline)]" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                   )}>
            <UPLOAD.icon size={16} strokeWidth={1.9} /><span className="truncate">{UPLOAD.short}</span>
          </NavLink>
          <IconButton label={resolvedTheme(theme.theme) === "dark" ? "Thème clair" : "Thème sombre"} onClick={theme.toggle}>
            {resolvedTheme(theme.theme) === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </IconButton>
          <RefreshButton compact />
        </div>
      </div>
    </aside>
  );
}

/** Re-ingest inbox/ and restart the server, then come back. */
function RefreshButton({ compact }: { compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    const id = toast.loading("Lecture des relevés…");
    try {
      const r = await send<{ added: number; restarting: boolean; error: string; movements: number }>(
        "/api/refresh?restart=0");
      toast.success(r.added ? `${r.added} mouvement${r.added > 1 ? "s" : ""} ajouté${r.added > 1 ? "s" : ""}` : "Rien de nouveau dans inbox/",
        { id, description: `${r.movements} mouvements au total` });
    } catch (e) {
      toast.error("La lecture a échoué", { id, description: String((e as Error).message) });
    } finally {
      setBusy(false);
    }
  };
  if (compact) {
    return (
      <IconButton label="Relire les relevés" onClick={run} disabled={busy}>
        <RefreshCw size={17} className={busy ? "animate-spin" : ""} />
      </IconButton>
    );
  }
  return (
    <button type="button" onClick={run} disabled={busy}
            className="flex h-9 items-center gap-3 rounded-xl px-3 text-[14px] font-medium text-ink-2 transition hover:bg-surface-2 hover:text-ink disabled:opacity-50">
      <RefreshCw size={17} className={busy ? "animate-spin" : ""} />
      Relire les relevés
    </button>
  );
}

function TopBar({
  desktop, periodPage, title, onSearch,
}: { desktop: boolean; periodPage: boolean; title: string; onSearch: () => void }) {
  const path = useLocation().pathname;
  const savingsPage = path.startsWith("/epargne");
  const forecastPage = path.startsWith("/previsions");
  return (
    <header className="safe-t sticky top-0 z-30 border-b border-hairline bg-[var(--glass)] backdrop-blur-xl backdrop-saturate-150">
      <div className={cx(
        "mx-auto flex h-14 w-full max-w-[1280px] items-center gap-2",
        desktop ? "px-6 lg:px-10" : "px-2",
      )}>
        {periodPage ? (
          <>
            <PeriodSwitcher compact={!desktop} />
            {savingsPage && <PocketPicker compact={!desktop} />}
          </>
        ) : forecastPage ? (
          <>
            {desktop && <span className="shrink-0 px-2 text-[16px] font-semibold tracking-tight">{title}</span>}
            <HorizonPicker compact={!desktop} />
            <ScenarioPicker compact={!desktop} />
            <RatePicker compact={!desktop} />
          </>
        ) : (
          <span className="truncate px-2 text-[16px] font-semibold tracking-tight">{title}</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {!desktop && (
            <IconButton label="Rechercher" onClick={onSearch}><Search size={18} /></IconButton>
          )}
        </div>
      </div>
    </header>
  );
}

function TabBar({ theme, onSearch }: { theme: ReturnType<typeof useTheme>; onSearch: () => void }) {
  const location = useLocation();
  const { pageHref } = useView();
  const [more, setMore] = useState(false);
  const tabs = TABS.map((to) => NAV.find((n) => n.to === to)!);
  const moreActive = !tabs.some((t) => isActive(t.to, location.pathname));
  const rest = NAV.filter((n) => !TABS.includes(n.to));

  return (
    <>
      <nav aria-label="Navigation principale"
           className="safe-b fixed inset-x-0 bottom-0 z-40 border-t border-hairline bg-[var(--glass)] backdrop-blur-xl backdrop-saturate-150">
        <div className="mx-auto grid h-[60px] max-w-lg grid-cols-5">
          {tabs.map((item) => {
            const active = isActive(item.to, location.pathname);
            return (
              <NavLink key={item.to} to={pageHref(item.to)} aria-current={active ? "page" : undefined}
                       className={cx("relative flex flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium no-underline",
                         active ? "text-ink" : "text-muted")}>
                {active && <motion.span layoutId="tab-active" className="absolute top-0 h-[2.5px] w-8 rounded-full bg-ink"
                                        transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
                <item.icon size={22} strokeWidth={active ? 2.1 : 1.8} />
                {item.short ?? item.label}
              </NavLink>
            );
          })}
          <button type="button" onClick={() => setMore(true)}
                  className={cx("relative flex flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium",
                    moreActive ? "text-ink" : "text-muted")}>
            {moreActive && <span className="absolute top-0 h-[2.5px] w-8 rounded-full bg-ink" />}
            <Ellipsis size={22} />
            Plus
          </button>
        </div>
      </nav>
      <Sheet open={more} onOpenChange={setMore} title="Plus">
        <div className="grid grid-cols-2 gap-2">
          {[...rest, { ...UPLOAD, to: UPLOAD.to }].map((item) => (
            <Link key={item.to} to={pageHref(item.to)} onClick={() => setMore(false)}
                  className="flex flex-col gap-2 rounded-2xl border border-hairline bg-surface-2/50 p-4 no-underline active:scale-[0.98]">
              <item.icon size={22} strokeWidth={1.8} />
              <span className="text-[14px] font-medium">{item.label}</span>
            </Link>
          ))}
          <Link to="/corrections/tri" onClick={() => setMore(false)}
                className="flex flex-col gap-2 rounded-2xl border border-hairline bg-surface-2/50 p-4 no-underline active:scale-[0.98]">
            <Wand2 size={22} strokeWidth={1.8} />
            <span className="text-[14px] font-medium">Trier les Twint</span>
          </Link>
        </div>
        <div className="mt-3 flex flex-col divide-y divide-hairline rounded-2xl border border-hairline">
          <button type="button" onClick={() => { setMore(false); onSearch(); }}
                  className="flex h-12 items-center gap-3 px-4 text-[14.5px]"><Search size={18} /> Rechercher</button>
          <button type="button" onClick={theme.toggle}
                  className="flex h-12 items-center gap-3 px-4 text-[14.5px]">
            {resolvedTheme(theme.theme) === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            {resolvedTheme(theme.theme) === "dark" ? "Thème clair" : "Thème sombre"}
          </button>
          <div className="flex h-12 items-center gap-3 px-4 text-[14.5px]"><RefreshButton compact /> Relire les relevés</div>
        </div>
      </Sheet>
    </>
  );
}
