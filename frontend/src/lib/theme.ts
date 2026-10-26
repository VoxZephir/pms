import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const KEY = "pms-theme";
const COLORS = { light: "#f9f9f7", dark: "#0d0d0d" };

function read(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  // The phone's status bar takes the page's colour, so the app runs to the
  // top edge in either theme.
  const metas = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  metas.forEach((m) => {
    const scheme = m.media.includes("dark") ? "dark" : "light";
    m.content = theme === "system" ? COLORS[scheme] : COLORS[theme];
  });
}

export function resolvedTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    apply(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  /** Light <-> dark, from whatever is on screen now. */
  const toggle = useCallback(() => {
    setTheme((t) => (resolvedTheme(t) === "dark" ? "light" : "dark"));
  }, []);
  return { theme, setTheme, toggle };
}
