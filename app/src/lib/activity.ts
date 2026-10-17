import { useEffect, useMemo, useState } from "react";

import { readActivity, type ActivityEntry, type ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";

const POLL_MS = 1000;

/** One step the activity panel shows: an entry, and for a tool call its result once it has arrived. */
export type Step = { entry: ActivityEntry; result: ActivityEntry | null };

type Read = {
  name: string;
  entries: ActivityEntry[];
  model: ModelSummary;
};

function callKey(entry: ActivityEntry): string {
  return `${entry.run_id}:${String(entry.data.id)}`;
}

/** Every entry but tool results, each of which rides on the call it ends. */
function pair(entries: ActivityEntry[]): Step[] {
  const results = new Map<string, ActivityEntry>();
  for (const entry of entries) {
    if (entry.kind === "tool-result") {
      results.set(callKey(entry), entry);
    }
  }
  return entries
    .filter((entry) => entry.kind !== "tool-result")
    .map((entry) => ({
      entry,
      result:
        entry.kind === "tool" ? (results.get(callKey(entry)) ?? null) : null,
    }));
}

/**
 * The activity of the model named `name`, polled from where the last read left off while it is in view, and read
 * again from the start when the model changes.
 */
export function useActivity(name: string | null): {
  steps: Step[];
  model: ModelSummary | null;
  working: Step[];
  error: string | null;
} {
  const [read, setRead] = useState<Read | null>(null);
  const [error, setError] = useState<{ name: string; text: string } | null>(
    null,
  );

  useEffect(() => {
    if (name === null) {
      return;
    }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = "";
    let entries: ActivityEntry[] = [];

    const poll = async () => {
      try {
        const fresh = await readActivity(name, cursor || undefined);
        if (stopped) {
          return;
        }
        cursor = fresh.cursor;
        if (fresh.entries.length > 0) {
          entries = [...entries, ...fresh.entries];
        }
        setRead({ name, entries, model: fresh.model });
        setError(null);
      } catch (cause) {
        if (stopped) {
          return;
        }
        // From the start next time, in case the model was replaced and the cursor points into what is gone.
        cursor = "";
        entries = [];
        setError({
          name,
          text: `Could not read the activity: ${describe(cause)}`,
        });
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
  }, [name]);

  const current = read !== null && read.name === name ? read : null;
  const steps = useMemo(() => pair(current?.entries ?? []), [current]);
  const model = current?.model ?? null;
  const latest = steps.at(-1)?.entry.run_id;
  // Calls of the latest run with no result yet, while the model says it is working; the agent can run several at once.
  const working =
    model?.status === "running"
      ? steps.filter(
          (step) =>
            step.entry.kind === "tool" &&
            step.result === null &&
            step.entry.run_id === latest,
        )
      : [];
  return {
    steps,
    model,
    working,
    error: error !== null && error.name === name ? error.text : null,
  };
}
