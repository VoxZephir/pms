import {
  BookOpen, CalendarClock, ChartColumnBig, EyeOff, Gift, Landmark, Luggage, House, PiggyBank, ReceiptText, Sparkles, Tags, TrendingUp, Upload, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  short?: string;
  icon: LucideIcon;
  /** The page reads the window: the period switcher shows on it. */
  period?: boolean;
  /** Folded under "Plus" in the sidebar: pages opened now and then. Ten
   * entries squeezed the page's own contents to a few lines. */
  more?: boolean;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Tableau de bord", short: "Accueil", icon: House, period: true },
  { to: "/transactions", label: "Transactions", icon: ReceiptText, period: true },
  { to: "/epargne", label: "Épargne", icon: PiggyBank, period: true },
  { to: "/a-venir", label: "À venir", icon: CalendarClock },
  { to: "/analyse", label: "Analyse", icon: ChartColumnBig },
  { to: "/previsions", label: "Prévisions", icon: TrendingUp },
  { to: "/projets", label: "Projets", icon: Luggage, more: true },
  { to: "/impots", label: "Impôts", icon: Landmark, more: true },
  { to: "/bilan", label: "Bilan de l'année", icon: Gift, more: true },
  { to: "/corrections", label: "Corrections", icon: Tags, more: true },
  { to: "/assistant", label: "Assistant", icon: Sparkles, more: true },
  { to: "/caviarder", label: "Caviarder un PDF", icon: EyeOff, more: true },
  { to: "/aide", label: "Manuel", icon: BookOpen, more: true },
];

export const UPLOAD: NavItem = { to: "/importer", label: "Importer un relevé", short: "Importer", icon: Upload };

/** The phone's tab bar: four destinations and "Plus" -- five is what a
 * thumb can tell apart without reading. */
export const TABS = ["/", "/transactions", "/epargne", "/previsions"];

export function isActive(item: string, pathname: string): boolean {
  // A day is opened from the dashboard (its calendar, its columns): it lights
  // the home tab, not "Plus".
  if (item === "/") return pathname === "/" || pathname.startsWith("/jour/");
  return pathname === item || pathname.startsWith(`${item}/`);
}

/** Where the manual speaks of a page: its card on `/aide`. */
export function helpAnchor(path: string): string {
  if (path === "/" || path.startsWith("/jour/")) return "p-accueil";
  const page = [...NAV, UPLOAD].find((n) => n.to !== "/" && isActive(n.to, path));
  return page ? `p-${page.to.slice(1)}` : "principe";
}
