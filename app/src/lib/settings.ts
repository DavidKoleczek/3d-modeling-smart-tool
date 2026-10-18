import { useSyncExternalStore } from "react";

import { readAppSettings, saveAppSettings, type AppSettings } from "@/lib/api";
import { describe } from "@/lib/errors";
import { setThemePreference } from "@/lib/theme";

const SAVE_DELAY_MS = 400;

/** `AppSettings()` in schemas.py, for when they cannot be read. */
export const DEFAULT_SETTINGS: AppSettings = {
  theme: "system",
  grid: true,
  wireframe: false,
  dimensions: false,
  wide: {
    models: { size: null, open: true },
    activity: { size: null, open: true },
  },
  medium: {
    models: { size: null, open: true },
    activity: { size: null, open: true },
  },
  steps: {},
};

type State = {
  settings: AppSettings;
  error: string | null;
  /** Counts layout resets, so the panes can start over from their defaults. */
  layouts: number;
};

const listeners = new Set<() => void>();
let state: State = { settings: DEFAULT_SETTINGS, error: null, layouts: 0 };
let timer: ReturnType<typeof setTimeout> | undefined;
// Changed here and not yet saved, or being saved: a read meanwhile would undo the change.
let unsaved = false;
let saving = 0;

function set(next: State) {
  state = next;
  setThemePreference(next.settings.theme);
  for (const listener of listeners) {
    listener();
  }
}

/** Read the person's settings, before the view first paints so it opens in their theme and layout. */
export async function loadSettings(): Promise<void> {
  try {
    const settings = await readAppSettings();
    if (!unsaved && saving === 0) {
      set({ ...state, settings });
    }
  } catch {
    // The defaults stand in until the next read, when the app gets focus again.
  }
}

async function save() {
  unsaved = false;
  saving += 1;
  try {
    await saveAppSettings(state.settings);
    if (state.error) {
      set({ ...state, error: null });
    }
  } catch (cause) {
    set({ ...state, error: `Could not save the settings. ${describe(cause)}` });
  } finally {
    saving -= 1;
  }
}

/** Change the settings at once, and save them once the person stops changing them. */
export function updateSettings(change: (current: AppSettings) => AppSettings) {
  set({ ...state, settings: change(state.settings) });
  unsaved = true;
  clearTimeout(timer);
  timer = setTimeout(() => void save(), SAVE_DELAY_MS);
}

/** Put every pane back to its default size, open. */
export function resetLayout() {
  updateSettings((current) => ({
    ...current,
    wide: DEFAULT_SETTINGS.wide,
    medium: DEFAULT_SETTINGS.medium,
  }));
  set({ ...state, layouts: state.layouts + 1 });
}

// Another app open on this machine may have changed them, which shows here once this one gets focus.
window.addEventListener("focus", () => void loadSettings());
// A change made just before the view goes away is saved now rather than lost with the timer.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && unsaved) {
    clearTimeout(timer);
    void save();
  }
});

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useSettings(): State {
  return useSyncExternalStore(subscribe, () => state);
}
