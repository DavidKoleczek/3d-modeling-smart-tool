import { useEffect, useRef, useState } from "react";

import {
  chooseIntelligenceModel,
  listIntelligenceModels,
  type IntelligenceChoice,
  type AppIntelligence,
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
  /** What the next request runs with: the person's last pick in the directory, else the default; null until read. */
  choice: IntelligenceChoice | null;
  error: string | null;
  choose: (model: string, reasoningEffort: ReasoningEffort) => void;
  /** The reasoning efforts the chosen model takes. */
  efforts: ReasoningEffort[];
  /** A model's name as the picker shows it, or its id when it offers no such model. */
  label: (model: string) => string;
};

/** The AI models and reasoning efforts to pick from, and the pick, remembered in the app's directory. */
export function useIntelligence(): Intelligence {
  const [options, setOptions] = useState<AppIntelligence | null>(null);
  const [picked, setPicked] = useState<IntelligenceChoice | null>(null);
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
      agent_provider: offered.agent_provider,
      model,
      reasoning_effort: effort,
    });
    setError(null);
    recording.current = recording.current.then(() =>
      chooseIntelligenceModel(model, effort).then(
        setOptions,
        (cause: unknown) => setError(describe(cause)),
      ),
    );
  };

  const choice = picked ?? options?.chosen ?? options?.default ?? null;
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
