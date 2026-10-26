/** In-page navigation, built from what the page actually drew.
 *
 * Every `Panel` marks itself `data-section`; the list is read from the DOM
 * rather than declared per page, so a panel the API gated out (too short a
 * window) is absent from the contents too, and a new panel needs no entry
 * anywhere. The section in view is the last one whose top has passed under
 * the sticky bar. Jumping to a folded panel unfolds it. */
import { ArrowUp, ListTree } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { Sheet } from "@/components/Sheet";
import { cx } from "@/components/ui";

export interface Section { id: string; title: string }

/** Below the sticky top bar (56 px) with some air: what counts as "reached". */
const LINE = 104;

/** The section last jumped to. Near the end of a page a panel cannot scroll
 * up to the line, and "the last one past it" would mark another: the one
 * asked for stays marked until the reader scrolls by hand. */
let target: string | null = null;

function read(): Section[] {
  const out: Section[] = [];
  document.querySelectorAll<HTMLElement>("#main [data-section]").forEach((el) => {
    const title = el.querySelector("h2")?.textContent?.trim();
    if (el.id && title) out.push({ id: el.id, title });
  });
  return out;
}

function same(a: Section[], b: Section[]) {
  return a.length === b.length && a.every((s, i) => s.id === b[i].id && s.title === b[i].title);
}

export function useSections() {
  const location = useLocation();
  const [sections, setSections] = useState<Section[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const main = document.getElementById("main");
    if (!main) return;
    let frame = 0;
    const collect = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setSections((prev) => {
        const next = read();
        return same(prev, next) ? prev : next;
      }));
    };
    collect();
    const observer = new MutationObserver(collect);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [location.pathname]);

  useEffect(() => {
    let frame = 0;
    const spy = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setScrolled(window.scrollY > window.innerHeight * 0.6);
        const bottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
        let current: string | null = null;
        for (const s of sections) {
          const el = document.getElementById(s.id);
          if (el && el.getBoundingClientRect().top <= LINE) current = s.id;
        }
        if (bottom && sections.length) current = sections[sections.length - 1].id;
        if (target && document.getElementById(target)) current = target;
        setActive(current);
      });
    };
    // The jump's own smooth scroll keeps the pin; the reader's hand drops it.
    const release = () => { target = null; };
    const hand = ["wheel", "touchmove", "keydown", "pointerdown"] as const;
    spy();
    window.addEventListener("scroll", spy, { passive: true });
    window.addEventListener("resize", spy);
    hand.forEach((e) => window.addEventListener(e, release, { passive: true }));
    return () => {
      window.removeEventListener("scroll", spy);
      window.removeEventListener("resize", spy);
      hand.forEach((e) => window.removeEventListener(e, release));
      cancelAnimationFrame(frame);
    };
  }, [sections]);

  return { sections, active, scrolled };
}

function smooth(): ScrollBehavior {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

export function goToSection(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  target = id;
  el.dispatchEvent(new Event("section:open"));
  glide(() => {
    const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
    return el.getBoundingClientRect().top + window.scrollY - margin;
  });
  window.dispatchEvent(new Event("scroll"));  // already in place: mark it anyway
}

export function toTop() {
  glide(() => 0);
}

let gliding = 0;

/** Scroll to where `destination` says, re-asked every frame. The browser's
 * smooth scroll would not do: a folded panel that unfolds has motion measure
 * its height and put the window back where it was -- several times, as its
 * content arrives -- and each reset cancels a native smooth scroll for good.
 * Here a reset or a shift of layout is caught up on the next frame. */
function glide(destination: () => number) {
  const run = ++gliding;
  const stop = () => { gliding++; };
  const hand = ["wheel", "touchstart", "keydown"] as const;
  hand.forEach((e) => window.addEventListener(e, stop, { once: true, passive: true }));
  const done = () => hand.forEach((e) => window.removeEventListener(e, stop));
  const max = () => document.documentElement.scrollHeight - window.innerHeight;
  if (smooth() === "auto") {
    window.scrollTo(0, Math.min(destination(), max()));
    window.setTimeout(() => { if (run === gliding) window.scrollTo(0, Math.min(destination(), max())); done(); }, 300);
    return;
  }
  const from = window.scrollY;
  const t0 = performance.now();
  const ms = 420;
  const step = (now: number) => {
    if (run !== gliding) return done();
    const t = Math.min(1, (now - t0) / ms);
    const ease = 1 - Math.pow(1 - t, 3);
    const to = Math.min(destination(), max());
    window.scrollTo(0, from + (to - from) * ease);
    // Past the end, keep holding the target a little while content settles.
    if (now - t0 < ms + 250) requestAnimationFrame(step);
    else done();
  };
  requestAnimationFrame(step);
}

/** The contents in the sidebar: the page's sections, the one in view marked. */
export function SectionList({ sections, active, onPick }: {
  sections: Section[]; active: string | null; onPick?: () => void;
}) {
  return (
    <ul className="flex flex-col gap-0.5">
      {sections.map((s) => (
        <li key={s.id}>
          <a href={`#${s.id}`}
             aria-current={s.id === active ? "location" : undefined}
             onClick={(e) => {
               e.preventDefault();
               if (!onPick) return goToSection(s.id);
               // The sheet locks the page's scroll while it closes: jump after.
               onPick();
               window.setTimeout(() => goToSection(s.id), 320);
             }}
             className={cx(
               "relative block truncate rounded-lg pl-3 pr-2 no-underline transition",
               onPick ? "py-2.5 text-[15px]" : "py-1.5 text-[13px]",
               s.id === active ? "font-medium text-ink" : "text-muted hover:text-ink",
             )}>
            <span className={cx("absolute inset-y-1.5 left-0 w-[2px] rounded-full transition",
                                s.id === active ? "bg-ink" : "bg-hairline-2")} />
            {s.title}
          </a>
        </li>
      ))}
    </ul>
  );
}

/** Back to the top, once the page has been scrolled. On the phone the same
 * button opens the contents, whose first line is the top of the page. */
export function ScrollDock({ desktop, sections, active, scrolled }: {
  desktop: boolean; sections: Section[]; active: string | null; scrolled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const contents = !desktop && sections.length > 1;
  return (
    <>
      <AnimatePresence>
        {scrolled && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.96 }} transition={{ duration: 0.15 }}
            className={cx(
              "fixed right-4 z-30 flex overflow-hidden rounded-full border border-hairline bg-[var(--glass)] shadow-pop backdrop-blur-xl",
              desktop ? "bottom-6 right-6" : "bottom-[calc(72px+env(safe-area-inset-bottom))]",
            )}
          >
            {contents && (
              <button type="button" onClick={() => setOpen(true)} aria-label="Sections de la page"
                      className="grid h-11 w-11 place-items-center text-ink-2 active:bg-surface-2">
                <ListTree size={18} />
              </button>
            )}
            <button type="button" onClick={toTop} aria-label="Haut de page" title="Haut de page"
                    className={cx("grid h-11 w-11 place-items-center text-ink-2 transition hover:text-ink active:bg-surface-2",
                                  contents && "border-l border-hairline")}>
              <ArrowUp size={18} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
      {contents && (
        <Sheet open={open} onOpenChange={setOpen} title="Sur cette page">
          <SectionList sections={sections} active={active} onPick={() => setOpen(false)} />
        </Sheet>
      )}
    </>
  );
}
