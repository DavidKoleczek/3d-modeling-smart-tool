import { useEffect, useState, useSyncExternalStore } from "react";

import {
  keepUpload,
  readAppLibrary,
  readReferenceFile,
  saveAppPins,
  type AppLibrary,
  type AppPins,
  type ModelMode,
  type ModelSummary,
  type PinnedFolder,
  type ReferenceEntry,
} from "@/lib/api";
import { describe } from "@/lib/errors";
import { pathSource, sourceOf, type Reference } from "@/lib/references";

const IMAGE = /\.(png|jpe?g|gif|webp)$/i;

const EMPTY: AppLibrary = {
  references: [],
  folders: [],
  prompts: [],
  used: [],
  last_prompt: null,
};

/** Something in the library to pick: a model here, or a file or folder on this machine by its path. */
export type LibraryItem =
  | { key: string; kind: "model"; name: string }
  | { key: string; kind: "file" | "folder"; name: string; path: string };

type State = { library: AppLibrary | null; error: string | null };

const listeners = new Set<() => void>();
let state: State = { library: null, error: null };
let reading: Promise<void> | null = null;
// Saves go one at a time, in order, so the last pin made is the one kept.
let saving: Promise<unknown> = Promise.resolve();
// The app's directory the library was read for, since each directory keeps its own pins and uses.
let followed: string | null = null;

function set(next: Partial<State>) {
  state = { ...state, ...next };
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

/** Read the library again, as once files were chosen, which it now offers as used before. */
export function refreshLibrary(): Promise<void> {
  reading = readAppLibrary().then(
    (library) => set({ library, error: null }),
    (cause: unknown) =>
      set({ error: `Could not read the library: ${describe(cause)}` }),
  );
  return reading;
}

/** Read the library again once the app shows another directory, whose pins and uses are its own. */
export function followDirectory(directory: string | null) {
  if (directory === null || directory === followed) {
    return;
  }
  const switched = followed !== null;
  followed = directory;
  if (switched) {
    void refreshLibrary();
  }
}

/**
 * What the app offers to start a request from: what was pinned and used in its directory, and the last prompt a model
 * was created from there, read once and kept current as the person pins.
 */
export function useLibrary(): { library: AppLibrary; error: string | null } {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (reading === null) {
      void refreshLibrary();
    }
  }, []);
  return { library: current.library ?? EMPTY, error: current.error };
}

/** Show the pins `change` makes at once, and keep them, reading them again should they not be kept. */
function changePins(change: (pins: AppPins) => AppPins) {
  const library = state.library ?? EMPTY;
  const pins = change({
    references: library.references,
    folders: library.folders,
    prompts: library.prompts,
  });
  set({ library: { ...library, ...pins }, error: null });
  saving = saving
    .then(() => saveAppPins(pins))
    .catch((cause: unknown) => {
      set({ error: describe(cause) });
      return refreshLibrary();
    });
}

export function modelItem(name: string): LibraryItem {
  return { key: `model:${name}`, kind: "model", name };
}

export function entryItem(entry: ReferenceEntry): LibraryItem {
  return {
    key: pathSource(entry.path),
    kind: entry.kind,
    name: entry.name,
    path: entry.path,
  };
}

/** The last part of a path, as a name to show. */
export function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/** The pinned references as items to pick, leaving out models pinned in another directory. */
export function pinnedItems(
  library: AppLibrary,
  models: ModelSummary[],
): LibraryItem[] {
  return library.references.flatMap((pinned): LibraryItem[] => {
    if (pinned.kind !== "model") {
      return [
        entryItem({
          name: baseName(pinned.path),
          path: pinned.path,
          kind: pinned.kind,
        }),
      ];
    }
    const model = models.find((entry) => entry.directory === pinned.path);
    return model ? [modelItem(model.name)] : [];
  });
}

/** The keys of the pinned items, as `pinnedItems` gives them. */
export function pinnedKeys(
  library: AppLibrary,
  models: ModelSummary[],
): Set<string> {
  return new Set(pinnedItems(library, models).map((item) => item.key));
}

function pathOf(item: LibraryItem, models: ModelSummary[]): string | null {
  if (item.kind !== "model") {
    return item.path;
  }
  return models.find((model) => model.name === item.name)?.directory ?? null;
}

/** Pin the item, or unpin it when it is pinned. */
export function togglePin(item: LibraryItem, models: ModelSummary[]) {
  const path = pathOf(item, models);
  if (path === null) {
    return;
  }
  changePins((pins) => {
    const kept = pins.references.filter((pinned) => pinned.path !== path);
    return {
      ...pins,
      references:
        kept.length < pins.references.length
          ? kept
          : [{ path, kind: item.kind }, ...kept],
    };
  });
}

/** The library item a reference is, when it can be pinned as it is; one dropped or pasted has to be kept first. */
export function itemOf(reference: Reference): LibraryItem | null {
  if (reference.kind === "model") {
    return modelItem(reference.name);
  }
  const source = sourceOf(reference);
  return source.startsWith("path:")
    ? entryItem({
        name: reference.name,
        path: source.slice("path:".length),
        kind: reference.kind,
      })
    : null;
}

/**
 * Pin a reference, or unpin it, keeping a copy of one dropped or pasted first, since it has no path of its own;
 * resolves with what identifies the copy, for the reference to carry, when one was kept.
 */
export async function togglePinOf(
  reference: Reference,
  models: ModelSummary[],
): Promise<string | null> {
  const item = itemOf(reference);
  if (item) {
    togglePin(item, models);
    return null;
  }
  const path = await keepUpload(reference.key);
  const kind = reference.kind === "folder" ? "folder" : "file";
  togglePin(entryItem({ name: reference.name, path, kind }), models);
  return pathSource(path);
}

export function pinFolder(path: string, shows: PinnedFolder["shows"]) {
  changePins((pins) => ({
    ...pins,
    folders: [
      ...pins.folders.filter((folder) => folder.path !== path),
      { path, shows },
    ],
  }));
}

export function unpinFolder(path: string) {
  changePins((pins) => ({
    ...pins,
    folders: pins.folders.filter((folder) => folder.path !== path),
  }));
}

export function isPinnedPrompt(
  library: AppLibrary,
  text: string,
  mode: ModelMode,
): boolean {
  return library.prompts.some(
    (prompt) => prompt.text === text.trim() && prompt.mode === mode,
  );
}

export function pinPrompt(text: string, mode: ModelMode) {
  const trimmed = text.trim();
  changePins((pins) =>
    !trimmed ||
    pins.prompts.some(
      (prompt) => prompt.text === trimmed && prompt.mode === mode,
    )
      ? pins
      : { ...pins, prompts: [...pins.prompts, { text: trimmed, mode }] },
  );
}

export function unpinPrompt(text: string, mode: ModelMode) {
  changePins((pins) => ({
    ...pins,
    prompts: pins.prompts.filter(
      (prompt) => !(prompt.text === text.trim() && prompt.mode === mode),
    ),
  }));
}

const thumbnails = new Map<string, Promise<string | null>>();

/** A picture of an image in the library by its path, once read; null for anything else, or one too large to show. */
export function useThumbnail(path: string | null): string | null {
  const [loaded, setLoaded] = useState<{
    path: string;
    url: string | null;
  } | null>(null);
  useEffect(() => {
    if (path === null || !IMAGE.test(path)) {
      return;
    }
    let thumbnail = thumbnails.get(path);
    if (!thumbnail) {
      thumbnail = readReferenceFile(path).catch(() => null);
      thumbnails.set(path, thumbnail);
    }
    let showing = true;
    void thumbnail.then((url) => {
      if (showing) {
        setLoaded({ path, url });
      }
    });
    return () => {
      showing = false;
    };
  }, [path]);
  return loaded?.path === path ? loaded.url : null;
}
