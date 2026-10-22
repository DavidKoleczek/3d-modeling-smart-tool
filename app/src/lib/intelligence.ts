import { useEffect, useRef, useState } from "react";

import {
  chooseIntelligenceModel,
  listIntelligenceModels,
  type IntelligenceChoice,
  type IntelligenceModel,
  type AppIntelligence,
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
   * What the next request runs with: the person's pick, else what the model in view last ran with, else their last
   * pick in the directory, else the default; null until read.
   */
  choice: IntelligenceChoice | null;
  error: string | null;
  choose: (model: string, reasoningEffort: ReasoningEffort) => void;
  /** The reasoning efforts the chosen model takes. */
  efforts: ReasoningEffort[];
  /** A model's name as the picker shows it, or its id when it offers no such model. */
  label: (model: string) => string;
};

/**
 * The AI models and reasoning efforts to pick from, and the pick, remembered in the app's directory. For a request on
 * `shown`, the pick starts on what its last run used, so a request goes on in that session unless the person picks
 * otherwise, and a pick they make lasts while that model is in view.
 */
export function useIntelligence(
  shown: ModelSummary | null = null,
): Intelligence {
  const [options, setOptions] = useState<AppIntelligence | null>(null);
  const [picked, setPicked] = useState<{
    model: string | null;
    choice: IntelligenceChoice;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One pick recorded at a time, so the last one made is the one the directory keeps.
  const recording = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    let stopped = false;
    listIntelligenceModels().then(
      (fresh) => {
        if (!stopped) {
          setOptions(fresh);
        }
      },
      (cause: unknown) => {
        if (!stopped) {
          setError(`Could not list the AI models: ${describe(cause)}`);
        }
      },
    );
    return () => {
      stopped = true;
    };
  }, []);

  const choose = (model: string, reasoningEffort: ReasoningEffort) => {
    const offered = options?.models.find((candidate) => candidate.id === model);
    if (!offered) {
      return;
    }
    const effort = nearestEffort(reasoningEffort, offered.reasoning_efforts);
    setPicked({
      model: shown?.name ?? null,
      choice: {
        agent_provider: offered.agent_provider,
        model,
        reasoning_effort: effort,
      },
    });
    setError(null);
    recording.current = recording.current.then(() =>
      chooseIntelligenceModel(model, effort).then(
        setOptions,
        (cause: unknown) => setError(describe(cause)),
      ),
    );
  };

  const last =
    shown?.last_run && options
      ? asOffered(shown.last_run, options.models)
      : null;
  const choice =
    (picked?.model === (shown?.name ?? null) ? picked.choice : null) ??
    last ??
    options?.chosen ??
    options?.default ??
    null;
  return {
    options,
    choice,
    error,
    choose,
    efforts:
      options?.models.find((candidate) => candidate.id === choice?.model)
        ?.reasoning_efforts ?? [],
    label: (model) =>
      options?.models.find((candidate) => candidate.id === model)?.label ??
      model,
  };
}
