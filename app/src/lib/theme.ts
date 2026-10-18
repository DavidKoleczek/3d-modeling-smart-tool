import { useSyncExternalStore } from "react";

import type { AppSettings } from "@/lib/api";

export type Theme = "light" | "dark";

/** What the person picked: System follows the host's theme. */
export type ThemePreference = AppSettings["theme"];

const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();
let hostTheme: Theme | null = null;
let preference: ThemePreference = "system";

/** The theme the view shows: the person's pick, or for System the host's, else the computer's. */
export function effectiveTheme(): Theme {
  if (preference !== "system") {
    return preference;
  }
  return hostTheme ?? (darkScheme.matches ? "dark" : "light");
}

function apply() {
  const theme = effectiveTheme();
  const root = document.documentElement;
  if (root.dataset.theme !== theme) {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    for (const listener of listeners) {
      listener();
    }
  }
}

/** Record the theme the host gives, which System follows. */
export function setHostTheme(theme: Theme) {
  hostTheme = theme;
  apply();
}

export function setThemePreference(next: ThemePreference) {
  preference = next;
  apply();
}

darkScheme.addEventListener("change", apply);
apply();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The theme in effect, rerendering when it changes. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, effectiveTheme);
}
