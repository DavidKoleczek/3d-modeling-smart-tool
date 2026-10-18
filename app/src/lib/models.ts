import { useCallback, useEffect, useRef, useState } from "react";

import {
  listModels,
  viewModel,
  type ModelListing,
  type ModelSummary,
} from "@/lib/api";
import { describe } from "@/lib/errors";

const POLL_MS = 1000;

/**
 * The models in the app's directory, polled, and which one is in view.
 *
 * The view opens on the model viewed last. After that it switches when the model viewed last changes to one it did
 * not pick itself, so `modeling-3d view-3d-model` from the host session brings a model up, and when a new model
 * appears, so a model the agent starts shows as it is built.
 */
export function useModels(): {
  listing: ModelListing | null;
  model: ModelSummary | null;
  error: string | null;
  pick: (name: string) => Promise<void>;
} {
  const [listing, setListing] = useState<ModelListing | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The last `last_viewed` the view saw or set; undefined before the first listing.
  const followed = useRef<string | null | undefined>(undefined);
  const known = useRef<Set<string> | null>(null);
  // A listing asked for before or while a pick is recorded still carries the old `last_viewed`, which must not undo it.
  const picks = useRef({ pending: 0, generation: 0 });

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const apply = (fresh: ModelListing, canFollow: boolean) => {
      const names = fresh.models.map((model) => model.name);
      const before = known.current;
      known.current = new Set(names);
      let target: string | null | undefined;
      if (before === null) {
        followed.current = fresh.last_viewed;
        target = fresh.last_viewed;
      } else if (canFollow && fresh.last_viewed !== followed.current) {
        followed.current = fresh.last_viewed;
        target = fresh.last_viewed ?? undefined;
      } else {
        target = names.find((name) => !before.has(name));
      }
      setListing(fresh);
      setError(null);
      setSelected((current) => {
        const next = target ?? current;
        return next !== null && names.includes(next)
          ? next
          : (names[0] ?? null);
      });
    };

    const poll = async () => {
      const asked = picks.current.generation;
      try {
        const fresh = await listModels();
        const canFollow =
          picks.current.pending === 0 && asked === picks.current.generation;
        if (!stopped) {
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
    setSelected(name);
    try {
      await viewModel(name);
    } catch (cause) {
      setError(`Could not record ${name} as viewed: ${describe(cause)}`);
    } finally {
      picks.current.pending -= 1;
      picks.current.generation += 1;
    }
  }, []);

  const model =
    listing?.models.find((entry) => entry.name === selected) ?? null;
  return { listing, model, error, pick };
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

// `NAME_PATTERN` in create.py.
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
