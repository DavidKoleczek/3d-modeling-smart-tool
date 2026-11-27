import { useSyncExternalStore } from "react";

import {
  changeWindowsApp,
  checkForUpdate,
  installAgentProvider,
  installSkill,
  installUpdate,
  readWindowsApp,
  removeSkill,
  type SkillMode,
  type WindowsApp,
} from "@/lib/api";
import { expectRestarts, tellHostOfRestart } from "@/lib/restart";

const WHILE_UPDATING_MS = 2000;

// Null when the server was started any other way than by the Windows app, as by an agent session.
let windowsApp: WindowsApp | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();

function show(next: WindowsApp | null) {
  windowsApp = next;
  for (const listener of listeners) {
    listener();
  }
  // An update that fails leaves this server running, which is only learned by asking again.
  if (next?.updating && timer === null) {
    timer = setTimeout(() => {
      timer = null;
      void refreshWindowsApp();
    }, WHILE_UPDATING_MS);
  }
}

/** Reads what the Windows app is like, before the app is first drawn. */
export async function loadWindowsApp() {
  await refreshWindowsApp();
  if (windowsApp) {
    expectRestarts();
  }
  // It looks for a newer version once a day, which a page left open hears of when it is come back to.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && windowsApp) {
      void refreshWindowsApp();
    }
  });
}

/** Reads it again, as it changes from its own menu too. What can't be read leaves it as it was. */
export async function refreshWindowsApp() {
  try {
    show(await readWindowsApp());
  } catch {
    // Kept as it was.
  }
}

export async function setStartAtSignIn(on: boolean) {
  show(await changeWindowsApp({ start_at_sign_in: on }));
}

export async function lookForUpdate() {
  show(await checkForUpdate());
}

/** The newer version ends this server and starts its own, so the page around the view is told to load again then. */
export async function update() {
  tellHostOfRestart();
  show(await installUpdate());
}

/** The tool is installed again with it, which ends this server and starts it again, as an update does. */
export async function addAgentProvider(agentProvider: string) {
  tellHostOfRestart();
  show(await installAgentProvider(agentProvider));
}

export async function setSkill(agents: string[], mode: SkillMode) {
  show(await installSkill(agents, mode));
}

export async function dropSkill() {
  show(await removeSkill());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The Windows app, when it is what started the server, rerendering when it changes. */
export function useWindowsApp(): WindowsApp | null {
  return useSyncExternalStore(subscribe, () => windowsApp);
}
