import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteModel,
  listModels,
  renameModel,
  viewModel,
  type ModelListing,
  type ModelSummary,
} from "@/lib/api";
import { describe } from "@/lib/errors";

const POLL_MS = 1000;

/** The model in view: by its id, which a rename keeps, once a listing has it, and by its name until then. */
type Selection = { id: string | null; name: string };

function selectedIn(
  listing: ModelListing,
  selection: Selection | null,
): ModelSummary | undefined {
  if (selection === null) {
    return undefined;
  }
  return (
    listing.models.find((model) => model.id === selection.id) ??
    listing.models.find((model) => model.name === selection.name)
  );
}

/**
 * The models in the app's directory, polled, which one is in view, and renaming and deleting them.
 *
 * The view opens on the model viewed last. After that it switches only when the person picks a model, or when the
 * model viewed last changes to one it did not pick itself, so `modeling-3d view-3d-model` from the host session brings
 * a model up. A model created or changed anywhere else never takes the view, so several can be worked on at once. It
 * follows the model in view by its id, so a rename, from here or anywhere else, keeps it in view.
 */
export function useModels(): {
  listing: ModelListing | null;
  model: ModelSummary | null;
  error: string | null;
  pick: (name: string) => Promise<void>;
  rename: (name: string, newName: string) => Promise<void>;
  remove: (name: string) => Promise<void>;
} {
  const [listing, setListing] = useState<ModelListing | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The last `last_viewed` the view saw or set; undefined before the first listing.
  const followed = useRef<string | null | undefined>(undefined);
  // A listing asked for before or while a pick is recorded still carries the old `last_viewed`, which must not undo it.
  const picks = useRef({ pending: 0, generation: 0 });
  // Counts the renames and deletes made here, so a listing asked for before one never brings back what it changed.
  const edits = useRef(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const apply = (fresh: ModelListing, canFollow: boolean) => {
      let target: ModelSummary | undefined;
      if (
        followed.current === undefined ||
        (canFollow && fresh.last_viewed !== followed.current)
      ) {
        followed.current = fresh.last_viewed;
        target = fresh.models.find((model) => model.name === fresh.last_viewed);
      }
      setListing(fresh);
      setError(null);
      setSelected((current) => {
        const next = target ?? selectedIn(fresh, current) ?? fresh.models[0];
        return next ? { id: next.id, name: next.name } : null;
      });
    };

    const poll = async () => {
      const asked = picks.current.generation;
      const edited = edits.current;
      try {
        const fresh = await listModels();
        const canFollow =
          picks.current.pending === 0 && asked === picks.current.generation;
        if (!stopped && edited === edits.current) {
          apply(fresh, canFollow);
        }
      } catch (cause) {
        if (!stopped) {
          setError(`Could not list the models: ${describe(cause)}`);
        }
      }
      if (!stopped) {
        timer = setTimeout(poll, POLL_MS);
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  const pick = useCallback(async (name: string) => {
    picks.current.pending += 1;
    followed.current = name;
    setSelected({ id: null, name });
    try {
      await viewModel(name);
    } catch (cause) {
      setError(`Could not record ${name} as viewed: ${describe(cause)}`);
    } finally {
      picks.current.pending -= 1;
      picks.current.generation += 1;
    }
  }, []);

  // Each shows at once, ahead of the next listing, and throws what refused it for the caller to show.
  const rename = useCallback(async (name: string, newName: string) => {
    const renamed = await renameModel(name, newName);
    edits.current += 1;
    if (followed.current === name) {
      followed.current = newName;
    }
    setListing(
      (current) =>
        current && {
          ...current,
          models: current.models.map((model) =>
            model.id === renamed.id ? renamed : model,
          ),
          last_viewed:
            current.last_viewed === name ? newName : current.last_viewed,
        },
    );
  }, []);

  const remove = useCallback(async (name: string) => {
    await deleteModel(name);
    edits.current += 1;
    if (followed.current === name) {
      followed.current = null;
    }
    setListing(
      (current) =>
        current && {
          ...current,
          models: current.models.filter((model) => model.name !== name),
          last_viewed:
            current.last_viewed === name ? null : current.last_viewed,
        },
    );
  }, []);

  const model = (listing && selectedIn(listing, selected)) ?? null;
  return { listing, model, error, pick, rename, remove };
}

/** A directory as the app shows it, by its last two folders, such as `toys\.modeling-3d`. */
export function shortDirectory(path: string): string {
  const separator = path.includes("\\") ? "\\" : "/";
  return path.split(separator).filter(Boolean).slice(-2).join(separator);
}

/** The models whose names hold `query`, ignoring case. */
export function matching(listing: ModelListing | null, query: string) {
  const needle = query.trim().toLowerCase();
  return (listing?.models ?? []).filter((model) =>
    model.name.toLowerCase().includes(needle),
  );
}

const PASTELS = [
  "bg-pastel-blue",
  "bg-pastel-lilac",
  "bg-pastel-rose",
  "bg-pastel-peach",
  "bg-pastel-butter",
  "bg-pastel-mint",
  "bg-pastel-sage",
  "bg-pastel-stone",
];

/** The same pastel for a name every time, so a model without a render keeps its color. */
export function pastelFor(name: string): string {
  let hash = 0;
  for (const character of name) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }
  return PASTELS[hash % PASTELS.length];
}

// `NAME_PATTERN` in record.py.
export const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const FILLER = new Set(
  "a an and the of with like in on for to from make me create build model 3d please this that it".split(
    " ",
  ),
);

/** A name for what `prompt` describes, from its first words, that no model in the directory has yet. */
export function suggestName(prompt: string, models: ModelSummary[]): string {
  const words = prompt.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  const telling = words.filter((word) => !FILLER.has(word));
  const base =
    (telling.length > 0 ? telling : words).slice(0, 3).join("-").slice(0, 40) ||
    "model";
  // Ignoring case, as the directory does on Windows and macOS.
  const taken = new Set(models.map((model) => model.name.toLowerCase()));
  let name = base;
  for (let suffix = 2; taken.has(name); suffix += 1) {
    name = `${base}-${suffix}`;
  }
  return name;
}

/** What is wrong with `name` as the new name of the model named `current`, for the person; null when nothing is. */
export function renameProblem(
  name: string,
  current: string,
  models: ModelSummary[],
): string | null {
  if (!name) {
    return "Type a name.";
  }
  if (!NAME.test(name)) {
    return "Use letters, digits, dots, dashes, and underscores, starting with a letter or digit.";
  }
  // Ignoring case, as the directory does on Windows and macOS, apart from the model itself, which may change its case.
  const taken = models.find(
    (model) =>
      model.name !== current && model.name.toLowerCase() === name.toLowerCase(),
  );
  return taken ? `${taken.name} is already taken.` : null;
}
