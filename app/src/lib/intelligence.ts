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
};

/** A reasoning effort as the person reads it. */
export function effortLabel(effort: ReasoningEffort): string {
  return EFFORT_LABELS[effort] ?? effort;
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
    setPicked({
      agent_provider: offered.agent_provider,
      model,
      reasoning_effort: reasoningEffort,
    });
    setError(null);
    recording.current = recording.current.then(() =>
      chooseIntelligenceModel(model, reasoningEffort).then(
        setOptions,
        (cause: unknown) => setError(describe(cause)),
      ),
    );
  };

  return {
    options,
    choice: picked ?? options?.chosen ?? options?.default ?? null,
    error,
    choose,
    label: (model) =>
      options?.models.find((candidate) => candidate.id === model)?.label ??
      model,
  };
}
