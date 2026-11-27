import { useEffect, useState, useSyncExternalStore } from "react";

import {
  chooseIntelligenceModel,
  listIntelligenceModels,
  type IntelligenceChoice,
  type IntelligenceModel,
  type AppIntelligence,
  type ModelMode,
  type ModelSummary,
  type ReasoningEffort,
} from "@/lib/api";
import { describe } from "@/lib/errors";

const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
  ultra: "Ultra",
};
// From least to most, the order the labels are in.
const EFFORT_ORDER = Object.keys(EFFORT_LABELS) as ReasoningEffort[];

/** A reasoning effort as the person reads it. */
export function effortLabel(effort: ReasoningEffort): string {
  return EFFORT_LABELS[effort] ?? effort;
}

/** The one of `offered` closest to `effort`, so switching models keeps the depth as near the same as it can. */
function nearestEffort(
  effort: ReasoningEffort,
  offered: ReasoningEffort[],
): ReasoningEffort {
  const rank = EFFORT_ORDER.indexOf(effort);
  const distance = (each: ReasoningEffort) =>
    Math.abs(EFFORT_ORDER.indexOf(each) - rank);
  return offered.reduce(
    (best, each) => (distance(each) < distance(best) ? each : best),
    offered[0] ?? effort,
  );
}

/**
 * What `run` used, as the picker offers it: its own model, else the first of its agent provider's, which can go on in
 * its session; null when the picker offers none of that agent provider's.
 */
function asOffered(
  run: IntelligenceChoice,
  models: IntelligenceModel[],
): IntelligenceChoice | null {
  const model =
    models.find((candidate) => candidate.id === run.model) ??
    models.find((candidate) => candidate.agent_provider === run.agent_provider);
  if (!model) {
    return null;
  }
  return {
    agent_provider: model.agent_provider,
    model: model.id,
    reasoning_effort: nearestEffort(
      run.reasoning_effort,
      model.reasoning_efforts,
    ),
  };
}

const PROVIDER_LABELS: Record<string, string> = {
  claude: "Claude",
  codex: "Codex",
};

/** An agent provider as the person reads it. */
export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

export type Intelligence = {
  options: AppIntelligence | null;
  /**
   * What the next request runs with: the person's pick in its mode, else what the model in view last ran with when that
   * was in the same mode, else their last pick for the mode in the directory, else the mode's default; null until read.
   */
  choice: IntelligenceChoice | null;
  error: string | null;
  choose: (model: string, reasoningEffort: ReasoningEffort) => void;
  /** The reasoning efforts the chosen model takes. */
  efforts: ReasoningEffort[];
  /** A model's name as the picker shows it, or its id when it offers no such model. */
  label: (model: string) => string;
};

// The AI models to pick from and the picks the directory keeps, shared, so a pick in one picker shows in the others.
type Listed = { options: AppIntelligence | null; error: string | null };

const listeners = new Set<() => void>();
let listed: Listed = { options: null, error: null };
let listing: Promise<void> | null = null;
// One pick recorded at a time, so the last one made is the one the directory keeps.
let recording: Promise<unknown> = Promise.resolve();

function publish(next: Partial<Listed>) {
  listed = { ...listed, ...next };
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

function list() {
  listing = listIntelligenceModels().then(
    (options) => publish({ options, error: null }),
    (cause: unknown) => {
      // Listed again by the next picker to show, should the server come back.
      listing = null;
      publish({ error: `Could not list the AI models: ${describe(cause)}` });
    },
  );
}

/**
 * The AI models and reasoning efforts to pick from, and the pick for a request in `mode`, remembered for that mode in
 * the app's directory. For a request on `shown`, the pick starts on what its last run used when that run was in `mode`,
 * so a request goes on in that session unless the person picks otherwise, and a pick they make lasts while that model
 * is in view in that mode. In another mode a request starts a fresh session, so it starts on that mode's own.
 */
export function useIntelligence(
  shown: ModelSummary | null,
  mode: ModelMode,
): Intelligence {
  const { options, error: unlisted } = useSyncExternalStore(
    subscribe,
    () => listed,
  );
  const [picked, setPicked] = useState<{
    model: string | null;
    mode: ModelMode;
    choice: IntelligenceChoice;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (listing === null) {
      list();
    }
  }, []);

  const choose = (model: string, reasoningEffort: ReasoningEffort) => {
    const offered = options?.models.find((candidate) => candidate.id === model);
    if (!offered) {
      return;
    }
    const effort = nearestEffort(reasoningEffort, offered.reasoning_efforts);
    setPicked({
      model: shown?.name ?? null,
      mode,
      choice: {
        agent_provider: offered.agent_provider,
        model,
        reasoning_effort: effort,
      },
    });
    setError(null);
    recording = recording.then(() =>
      chooseIntelligenceModel(mode, model, effort).then(
        (options) => publish({ options }),
        (cause: unknown) => setError(describe(cause)),
      ),
    );
  };

  const last =
    shown?.last_run?.mode === mode && options
      ? asOffered(shown.last_run, options.models)
      : null;
  const choice =
    (picked?.model === (shown?.name ?? null) && picked.mode === mode
      ? picked.choice
      : null) ??
    last ??
    options?.chosen[mode] ??
    options?.defaults[mode] ??
    null;
  return {
    options,
    choice,
    error: error ?? unlisted,
    choose,
    efforts:
      options?.models.find((candidate) => candidate.id === choice?.model)
        ?.reasoning_efforts ?? [],
    label: (model) =>
      options?.models.find((candidate) => candidate.id === model)?.label ??
      model,
  };
}
