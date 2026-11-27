import { useEffect, useSyncExternalStore } from "react";

import {
  chooseAppWorkspace,
  createAppWorkspace,
  forgetAppWorkspace,
  onWorkspaceLost,
  openAppWorkspace,
  readAppWorkspaces,
  showWorkspace,
  type AppWorkspaces,
} from "@/lib/api";
import { forgetToolCalls } from "@/lib/calls";
import { describe } from "@/lib/errors";
import { forgetImages } from "@/lib/images";
import { forgetIntelligence } from "@/lib/intelligence";
import { forgetLibrary } from "@/lib/library";
import { forgetSteps } from "@/lib/steps";

// How often the view asks for a workspace while it has none, so one opened from a session comes up.
const POLL_MS = 1000;

type State = {
  /** Null until read. */
  workspaces: AppWorkspaces | null;
  /** The workspace the view shows: the app's, null before one is picked or once its folder is gone. */
  shown: string | null;
  error: string | null;
  /** Whether a switch the person asked for is on its way. */
  switching: boolean;
};

const listeners = new Set<() => void>();
let state: State = {
  workspaces: null,
  shown: null,
  error: null,
  switching: false,
};
// Switches go one at a time, so the workspace shown is the one the server answered the last with.
let switching: Promise<unknown> = Promise.resolve();
let pending = 0;

function set(next: Partial<Omit<State, "shown">>) {
  const workspaces = next.workspaces ?? state.workspaces;
  const shown = workspaces?.current ?? null;
  if (shown !== state.shown) {
    // What the stores hold is the last workspace's, and their caches by model name would show its models for this
    // one's of the same name. Forgotten before the workspace renders, so nothing of the last one shows in it.
    forgetLibrary();
    forgetSteps();
    forgetIntelligence();
    forgetToolCalls();
    forgetImages();
    showWorkspace(shown);
  }
  state = { ...state, ...next, shown };
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Read the workspace the app shows, and those opened in it, again. */
export async function refreshWorkspaces(): Promise<void> {
  try {
    set({ workspaces: await readAppWorkspaces() });
  } catch (cause) {
    set({ error: `Could not read the workspaces: ${describe(cause)}` });
  }
}

// A call found the app on another workspace, as after a switch from another view or a session, or on one gone.
onWorkspaceLost(() => void refreshWorkspaces());

/** Switch the app as `ask` does, after any switch already on its way; resolves with whether it did. */
function switchTo(ask: () => Promise<AppWorkspaces>): Promise<boolean> {
  pending += 1;
  set({ switching: true, error: null });
  const asking = switching.then(ask).then(
    (workspaces) => {
      pending -= 1;
      set({ workspaces, switching: pending > 0 });
      return true;
    },
    (cause: unknown) => {
      pending -= 1;
      set({ error: describe(cause), switching: pending > 0 });
      return false;
    },
  );
  switching = asking;
  return asking;
}

/** Switch the app to the workspace at `path`; resolves with whether it did. */
export function openWorkspace(path: string): Promise<boolean> {
  return switchTo(() => openAppWorkspace(path));
}

/** Make the folder `name` in `parent` as a new workspace, and switch the app to it; resolves with whether it did. */
export function createWorkspace(
  name: string,
  parent: string,
): Promise<boolean> {
  return switchTo(() => createAppWorkspace(name, parent));
}

/** Ask the person for a workspace in their folder dialog, and switch to it; resolves with whether it did. */
export async function chooseWorkspace(): Promise<boolean> {
  set({ error: null });
  try {
    const path = await chooseAppWorkspace();
    return path !== null && (await openWorkspace(path));
  } catch (cause) {
    set({ error: describe(cause) });
    return false;
  }
}

/** Ask the person for the folder to make a new workspace in, in their folder dialog; null if they cancel. */
export async function chooseFolderForNew(): Promise<string | null> {
  set({ error: null });
  try {
    return await chooseAppWorkspace(true);
  } catch (cause) {
    set({ error: describe(cause) });
    return null;
  }
}

/** Drop the workspace at `path` from those offered, leaving its folder as it is. */
export async function forgetWorkspace(path: string): Promise<void> {
  try {
    set({ workspaces: await forgetAppWorkspace(path), error: null });
  } catch (cause) {
    set({ error: describe(cause) });
  }
}

/** The workspace the view shows, and those to switch to. */
export function useWorkspaces(): State {
  return useSyncExternalStore(subscribe, () => state);
}

/** While `waiting`, read the workspaces again every second, so one opened from a session or another view comes up. */
export function useWorkspaceWait(waiting: boolean) {
  useEffect(() => {
    if (!waiting) {
      return;
    }
    const timer = setInterval(() => void refreshWorkspaces(), POLL_MS);
    return () => clearInterval(timer);
  }, [waiting]);
}
