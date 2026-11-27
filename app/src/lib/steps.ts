import { useSyncExternalStore } from "react";

import { readActivitySteps, saveActivityStep } from "@/lib/api";

type Steps = Record<string, Record<string, boolean>>;

const listeners = new Set<() => void>();
let steps: Steps = {};
// Saves go one at a time, in order, so the last toggle made is the one kept.
let saving: Promise<unknown> = Promise.resolve();
// Toggled here and not yet saved: a read meanwhile would undo the toggle.
let unsaved = 0;
// Counts the workspaces shown, each keeping its own, so what was read or toggled for one never lands in the next.
let generation = 0;

function set(next: Steps) {
  steps = next;
  for (const listener of listeners) {
    listener();
  }
}

/** Read the steps opened or closed in the activity of each model in the app's workspace. */
export async function loadSteps(): Promise<void> {
  const asked = generation;
  try {
    const read = await readActivitySteps();
    if (unsaved === 0 && asked === generation) {
      set(read.steps);
    }
  } catch {
    // What was read before stands in until the next read, when the app gets focus again.
  }
}

/** Forget the steps, for a workspace shown next, which reads its own. */
export function forgetSteps() {
  generation += 1;
  saving = Promise.resolve();
  unsaved = 0;
  set({});
}

/** Open or close the group of steps `group` in the activity of the model `modelId` at once, and keep it. */
export function toggleSteps(modelId: string, group: string, open: boolean) {
  set({ ...steps, [modelId]: { ...steps[modelId], [group]: open } });
  const asked = generation;
  unsaved += 1;
  saving = saving
    .then(() =>
      asked === generation ? saveActivityStep(modelId, group, open) : null,
    )
    .then(
      (saved) => {
        if (asked !== generation) {
          return;
        }
        unsaved -= 1;
        if (unsaved === 0 && saved) {
          set(saved.steps);
        }
      },
      () => {
        if (asked !== generation) {
          return;
        }
        unsaved -= 1;
        return loadSteps();
      },
    );
}

// Another app open in the same workspace may have changed them, which shows here once this one gets focus.
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
