import { useSyncExternalStore } from "react";

import { readActivitySteps, saveActivityStep } from "@/lib/api";

type Steps = Record<string, Record<string, boolean>>;

const listeners = new Set<() => void>();
let steps: Steps = {};
// Saves go one at a time, in order, so the last toggle made is the one kept.
let saving: Promise<unknown> = Promise.resolve();
// Toggled here and not yet saved: a read meanwhile would undo the toggle.
let unsaved = 0;

function set(next: Steps) {
  steps = next;
  for (const listener of listeners) {
    listener();
  }
}

/** Read the steps opened or closed in the activity of each model in the app's directory. */
export async function loadSteps(): Promise<void> {
  try {
    const read = await readActivitySteps();
    if (unsaved === 0) {
      set(read.steps);
    }
  } catch {
    // What was read before stands in until the next read, when the app gets focus again.
  }
}

/** Open or close the group of steps `group` in the activity of the model `modelId` at once, and keep it. */
export function toggleSteps(modelId: string, group: string, open: boolean) {
  set({ ...steps, [modelId]: { ...steps[modelId], [group]: open } });
  unsaved += 1;
  saving = saving
    .then(() => saveActivityStep(modelId, group, open))
    .then(
      (saved) => {
        unsaved -= 1;
        if (unsaved === 0) {
          set(saved.steps);
        }
      },
      () => {
        unsaved -= 1;
        return loadSteps();
      },
    );
}

// Another app open in the same directory may have changed them, which shows here once this one gets focus.
window.addEventListener("focus", () => void loadSteps());

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** By model id, the groups of steps the person opened or closed in its activity, and which. */
export function useSteps(): Steps {
  return useSyncExternalStore(subscribe, () => steps);
}
