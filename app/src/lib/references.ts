import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
} from "react";

import {
  uploadReference,
  type ModelSummary,
  type StagedReference,
} from "@/lib/api";
import { describe } from "@/lib/errors";

// What is sent of a file at a time: a third more in base64, well under the 4 MB the server takes in one request.
const PIECE_BYTES = 2 * 1024 * 1024;
const IMAGE = /^image\/(png|jpeg|gif|webp)$/;
// A preview is read whole into the page, so a larger image shows an icon instead.
const PREVIEW_BYTES = 8 * 1024 * 1024;
// Beside hidden folders, what a folder leaves out, as `SKIPPED_FOLDERS` in create.py does for one named by path.
const SKIPPED_FOLDERS = new Set(["node_modules", "__pycache__"]);

/**
 * Something a request works from: a file or a folder sent to the server as the person drops or pastes it, one on this
 * machine the server staged by its path, or a model here.
 */
export type Reference = {
  key: string;
  kind: "file" | "folder" | "model";
  name: string;
  preview: string | null;
  files: number;
  /** The folders a folder left out, by name. */
  skipped: string[];
  bytes: number;
  sent: number;
  error: string | null;
  /** Its path, as `pathSource` gives it, for one staged by path or kept to pin, so the library shows it picked. */
  source: string | null;
  /** For a model, its id, which a rename keeps, so it goes by the name the model has now. */
  model?: string;
};

export type References = {
  items: Reference[];
  models: string[];
  error: string | null;
  uploading: boolean;
  addFiles: (files: Iterable<File>) => void;
  /**
   * Adds files and folders the server staged as uploads from their paths, such as those chosen in the file dialog,
   * leaving out any already added from the same path; returns the keys of those it added.
   */
  addStaged: (files: StagedReference[]) => string[];
  addDropped: (data: DataTransfer) => void;
  addModel: (name: string) => void;
  remove: (key: string) => void;
  /** Marks the reference `key` as the path `source`, once it is kept to pin. */
  tag: (key: string, source: string) => void;
  clear: () => void;
  /** Once every file has arrived, what the request names: the uploads, then the models. */
  ready: () => Promise<{ uploads: string[]; reference_models: string[] }>;
};

/** A file of a reference, at its path in the folder, or its name alone. */
type Entry = { path: string; file: File };

function readBase64(blob: Blob, name: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () =>
      reject(reader.error ?? new Error(`Could not read ${name}.`));
    reader.readAsDataURL(blob);
  });
}

/** Send `file` to the server as `path` in the upload `upload`, a piece at a time, while `going` says to. */
async function sendFile(
  upload: string,
  path: string,
  file: Blob,
  going: () => boolean,
  sent: (bytes: number) => void,
): Promise<void> {
  let offset = 0;
  // An empty file is still sent once, so it arrives.
  do {
    if (!going()) {
      return;
    }
    const piece = file.slice(offset, offset + PIECE_BYTES);
    await uploadReference(upload, path, offset, await readBase64(piece, path));
    offset += piece.size;
    sent(piece.size);
  } while (offset < file.size);
}

function uploadId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(8)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** What identifies a file or folder on this machine to the library, by its path. */
export function pathSource(path: string): string {
  return `path:${path}`;
}

/** What identifies a reference to the library: its path, or its own key, which a model's matches. */
export function sourceOf(reference: Reference): string {
  return reference.source ?? reference.key;
}

function skippedFolder(name: string): boolean {
  return name.startsWith(".") || SKIPPED_FOLDERS.has(name);
}

/** The models a request can work from: those in the directory with a script to read. */
export function referable(models: ModelSummary[]): ModelSummary[] {
  return models.filter((model) => model.files.includes("model.py"));
}

function entriesOf(
  directory: FileSystemDirectoryEntry,
): Promise<FileSystemEntry[]> {
  const reader = directory.createReader();
  const all: FileSystemEntry[] = [];
  return new Promise((resolve, reject) => {
    // Each read gives the next batch, and an empty one at the end.
    const next = () =>
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(all);
        } else {
          all.push(...batch);
          next();
        }
      }, reject);
    next();
  });
}

/** The files in a dropped folder, at their paths in it, leaving out the folders a folder leaves out. */
async function droppedFolder(
  directory: FileSystemDirectoryEntry,
): Promise<{ entries: Entry[]; skipped: Set<string> }> {
  const entries: Entry[] = [];
  const skipped = new Set<string>();
  const walk = async (folder: FileSystemDirectoryEntry, prefix: string) => {
    for (const entry of await entriesOf(folder)) {
      const path = `${prefix}/${entry.name}`;
      if (entry.isDirectory) {
        if (skippedFolder(entry.name)) {
          skipped.add(entry.name);
        } else {
          await walk(entry as FileSystemDirectoryEntry, path);
        }
      } else {
        const file = await new Promise<File>((resolve, reject) =>
          (entry as FileSystemFileEntry).file(resolve, reject),
        );
        entries.push({ path, file });
      }
    }
  };
  await walk(directory, directory.name);
  return { entries, skipped };
}

/**
 * The files, folders, and models a request is to work from, as the person adds them by dialog, drop, paste, or menu.
 * Each file or folder is sent to the server in pieces as soon as it is added, so a large one is on its way while
 * they write, and the request names it once it has arrived. A model it works from, of `listed`, follows a rename
 * by its id, and says so once it is deleted.
 */
export function useReferences(listed: ModelSummary[]): References {
  const [added, setItems] = useState<Reference[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Each upload's sending, which settles with what went wrong, if anything; removing a reference drops it here, which
  // stops its sending.
  const sending = useRef(new Map<string, Promise<string | null>>());
  // By key, the path each reference came from, kept apart from the items so one picked twice before the next render
  // is added once.
  const sourced = useRef(new Map<string, string>());
  // The models as last listed, for a model added by name to be kept by its id.
  const known = useRef(listed);

  useEffect(() => {
    known.current = listed;
  }, [listed]);

  const update = useCallback(
    (key: string, change: (item: Reference) => Partial<Reference>) =>
      setItems((current) =>
        current.map((item) =>
          item.key === key ? { ...item, ...change(item) } : item,
        ),
      ),
    [],
  );

  const send = useCallback(
    (reference: Reference, entries: Entry[]) => {
      const key = reference.key;
      setItems((current) => [...current, reference]);
      const run = async () => {
        for (const { path, file } of entries) {
          await sendFile(
            key,
            path,
            file,
            () => sending.current.has(key),
            (bytes) => update(key, (item) => ({ sent: item.sent + bytes })),
          );
        }
      };
      // Started once it is kept, so its first look finds it there.
      const task = Promise.resolve()
        .then(run)
        .then(
          () => null,
          (cause: unknown) => {
            const problem = describe(cause);
            update(key, () => ({ error: problem }));
            return problem;
          },
        );
      sending.current.set(key, task);
    },
    [update],
  );

  const addFiles = useCallback(
    (files: Iterable<File>) => {
      setError(null);
      for (const file of files) {
        const name = file.name || "pasted";
        const reference: Reference = {
          key: uploadId(),
          kind: "file",
          name,
          preview: null,
          files: 1,
          skipped: [],
          bytes: file.size,
          sent: 0,
          error: null,
          source: null,
        };
        send(reference, [{ path: name, file }]);
        if (IMAGE.test(file.type) && file.size <= PREVIEW_BYTES) {
          readBase64(file, name).then(
            (data) =>
              update(reference.key, () => ({
                preview: `data:${file.type};base64,${data}`,
              })),
            () => {},
          );
        }
      }
    },
    [send, update],
  );

  const addEntries = useCallback(
    (name: string, entries: Entry[], skipped: Set<string>) => {
      if (entries.length === 0) {
        setError(`${name} has no files to work from.`);
        return;
      }
      send(
        {
          key: uploadId(),
          kind: "folder",
          name,
          preview: null,
          files: entries.length,
          skipped: [...skipped].sort(),
          bytes: entries.reduce((sum, entry) => sum + entry.file.size, 0),
          sent: 0,
          error: null,
          source: null,
        },
        entries,
      );
    },
    [send],
  );

  const addStaged = useCallback((files: StagedReference[]) => {
    setError(null);
    const held = new Set(sourced.current.values());
    const added = files.filter((file) => !held.has(pathSource(file.path)));
    for (const file of added) {
      sending.current.set(file.upload, Promise.resolve(null));
      sourced.current.set(file.upload, pathSource(file.path));
    }
    setItems((current) => [
      ...current,
      ...added.map((file): Reference => ({
        key: file.upload,
        kind: file.kind,
        name: file.name,
        preview: file.preview,
        files: file.files,
        skipped: [],
        bytes: file.size,
        sent: file.size,
        error: null,
        source: pathSource(file.path),
      })),
    ]);
    return added.map((file) => file.upload);
  }, []);

  const addDropped = useCallback(
    (data: DataTransfer) => {
      setError(null);
      // Taken while the drop is handled: the browser empties the transfer once the handler returns.
      const files: File[] = [];
      const folders: FileSystemDirectoryEntry[] = [];
      for (const item of Array.from(data.items)) {
        const entry = item.kind === "file" ? item.webkitGetAsEntry() : null;
        const file = item.kind === "file" ? item.getAsFile() : null;
        if (entry?.isDirectory) {
          folders.push(entry as FileSystemDirectoryEntry);
        } else if (file) {
          files.push(file);
        }
      }
      addFiles(files);
      for (const folder of folders) {
        droppedFolder(folder).then(
          ({ entries, skipped }) => addEntries(folder.name, entries, skipped),
          (cause: unknown) =>
            setError(`${folder.name} couldn't be read. ${describe(cause)}`),
        );
      }
    },
    [addFiles, addEntries],
  );

  const addModel = useCallback((name: string) => {
    const id = known.current.find((model) => model.name === name)?.id;
    setItems((current) =>
      current.some(
        (item) =>
          item.kind === "model" &&
          (item.name === name || (id !== undefined && item.model === id)),
      )
        ? current
        : [
            ...current,
            {
              key: `model:${name}`,
              kind: "model",
              name,
              preview: null,
              files: 0,
              skipped: [],
              bytes: 0,
              sent: 0,
              error: null,
              source: null,
              model: id,
            },
          ],
    );
  }, []);

  const remove = useCallback((key: string) => {
    sending.current.delete(key);
    sourced.current.delete(key);
    setItems((current) => current.filter((item) => item.key !== key));
  }, []);

  const tag = useCallback(
    (key: string, source: string) => {
      sourced.current.set(key, source);
      update(key, () => ({ source }));
    },
    [update],
  );

  const clear = useCallback(() => {
    sending.current.clear();
    sourced.current.clear();
    setItems([]);
    setError(null);
  }, []);

  // A model goes by the name it has now, by its id, keeping the key it was added under. The library keys a model by
  // its name, so its source carries the new one for it to show as picked there.
  const items = added.map((item): Reference => {
    if (item.kind !== "model" || item.model === undefined) {
      return item;
    }
    const found = listed.find((model) => model.id === item.model);
    if (!found) {
      return { ...item, error: "It was deleted. Remove it to send." };
    }
    return found.name === item.name
      ? item
      : { ...item, name: found.name, source: `model:${found.name}` };
  });
  const models = items
    .filter((item) => item.kind === "model")
    .map((item) => item.name);

  const ready = useCallback(async () => {
    const uploads = [...sending.current.keys()];
    const problems = await Promise.all(sending.current.values());
    const failed = uploads.findIndex((_, index) => problems[index] !== null);
    if (failed !== -1) {
      const name = items.find((item) => item.key === uploads[failed])?.name;
      throw new Error(
        `${name ?? "A reference"} didn't arrive: ${problems[failed]} Remove it and add it again.`,
      );
    }
    return { uploads, reference_models: models };
  }, [items, models]);

  return {
    items,
    models,
    error,
    uploading: items.some(
      (item) => item.kind !== "model" && !item.error && item.sent < item.bytes,
    ),
    addFiles,
    addStaged,
    addDropped,
    addModel,
    remove,
    tag,
    clear,
    ready,
  };
}

/** Handlers that take files and folders dropped, and files pasted, onto an element; a paste of text alone is left to the field. */
export function takesReferences(references: References): {
  onDragOver: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
  onPaste: (event: ClipboardEvent) => void;
} {
  return {
    onDragOver: (event) => {
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
      }
    },
    onDrop: (event) => {
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
        references.addDropped(event.dataTransfer);
      }
    },
    onPaste: (event) => {
      if (event.clipboardData.files.length > 0) {
        event.preventDefault();
        references.addFiles(Array.from(event.clipboardData.files));
      }
    },
  };
}
