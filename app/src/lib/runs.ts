import type { IconName } from "@/components/ui/icon";
import type { Step } from "@/lib/activity";
import type { ActivityEntry, ModelStatus } from "@/lib/api";

const IMAGE = /\.(png|jpe?g|gif|webp)$/i;

/** A tool's verb for done and for under way, and its icon, by the name the agent gives the tool. */
const TOOLS: Record<string, { done: string; doing: string; icon: IconName }> = {
  Bash: { done: "Ran", doing: "Running", icon: "terminal" },
  Read: { done: "Read", doing: "Reading", icon: "file" },
  Edit: { done: "Edited", doing: "Editing", icon: "file-edit" },
  MultiEdit: { done: "Edited", doing: "Editing", icon: "file-edit" },
  Write: { done: "Wrote", doing: "Writing", icon: "file-edit" },
  Glob: { done: "Searched", doing: "Searching", icon: "search" },
  Grep: { done: "Searched", doing: "Searching", icon: "search" },
  commandExecution: { done: "Ran", doing: "Running", icon: "terminal" },
  fileChange: { done: "Edited", doing: "Editing", icon: "file-edit" },
  webSearch: { done: "Searched", doing: "Searching", icon: "search" },
};
const LOOK = { done: "Looked at", doing: "Looking at", icon: "image" as const };

export type CallState = "running" | "done" | "failed" | "unfinished";

/**
 * One step as a row shows it: a plain verb, what it worked on, and how it went. A tool call; one the agent is still
 * writing out, `size` characters of it so far; or a stretch of reasoning, whose `summary` is the agent's own once it is
 * done, when it gave one.
 */
export type Call = {
  kind: "tool" | "composing" | "reasoning";
  key: string;
  step: Step;
  verb: string;
  doing: string;
  icon: IconName;
  target: string;
  state: CallState;
  started: string;
  finished: string | null;
  error: string | null;
  summary: string | null;
  size: number | null;
};

/** What one entry in a run shows as, in order. */
export type Block =
  | { kind: "message"; entry: ActivityEntry }
  | { kind: "said"; entry: ActivityEntry }
  | {
      kind: "steps";
      key: string;
      calls: Call[];
      started: string;
      finished: string | null;
      state: "running" | "done" | "failed";
      /** Nothing has followed it yet in a run still working, so it stays open. */
      latest: boolean;
    }
  | { kind: "rebuilt"; time: string }
  | { kind: "ended"; entry: ActivityEntry; status: ModelStatus };

/** One request on a model and everything that came of it. */
export type Run = {
  id: string;
  number: number;
  request: ActivityEntry | null;
  started: string;
  ended: ActivityEntry | null;
  blocks: Block[];
  calls: Call[];
};

function call(step: Step, working: Set<Step>, ended: boolean): Call {
  const name = String(step.entry.data.name ?? "");
  const target = step.entry.text;
  const words =
    (name === "Read" && IMAGE.test(target)) || name === "imageView"
      ? LOOK
      : (TOOLS[name] ?? { done: name, doing: name, icon: "terminal" });
  const failed = step.result?.data.failed === true;
  let state: CallState = "done";
  if (failed) {
    state = "failed";
  } else if (working.has(step)) {
    state = "running";
  } else if (step.result === null) {
    state = ended ? "unfinished" : "running";
  }
  return {
    kind: "tool",
    key: `${step.entry.run_id}:${String(step.entry.data.id)}`,
    step,
    verb: words.done,
    doing: words.doing,
    icon: words.icon,
    target,
    state,
    started: step.entry.time,
    finished: step.result?.time ?? null,
    error: failed ? step.result?.text || null : null,
    summary: null,
    size: null,
  };
}

/** A tool call the agent is still writing out, as far as `step` says it has got. */
function composing(step: Step): Call {
  const name = String(step.entry.data.name ?? "");
  const words = TOOLS[name] ?? { done: name, doing: name, icon: "terminal" };
  return {
    kind: "composing",
    key: `${step.entry.run_id}:${String(step.entry.data.id)}`,
    step,
    verb: words.done,
    doing: words.doing,
    icon: words.icon,
    target: step.entry.text,
    state: "running",
    started: step.entry.time,
    finished: null,
    error: null,
    summary: null,
    size: Number(step.entry.data.characters ?? 0),
  };
}

/** The first line of a reasoning summary, without the Markdown that makes it a heading. */
function headline(summary: string): string {
  const line = summary.split("\n").find((each) => each.trim()) ?? "";
  return line
    .replace(/^#+\s*/, "")
    .replace(/\*\*|__/g, "")
    .trim();
}

/** A stretch of reasoning from `step`, its start, done once whatever came next arrived. */
function reasoning(step: Step, summary: string | null): Call {
  return {
    kind: "reasoning",
    key: `${step.entry.run_id}:reasoning:${step.entry.time}`,
    step,
    verb: "Reasoned",
    doing: "Reasoning",
    icon: "thought",
    target: summary === null ? "" : headline(summary),
    state: "running",
    started: step.entry.time,
    finished: null,
    error: null,
    summary,
    size: null,
  };
}

function reasoningState(call: Call, over: boolean): CallState {
  if (call.finished !== null) {
    return "done";
  }
  return over ? "unfinished" : "running";
}

/** The run's block of steps that the latest of them is in, or a new one after what came before, from `time`. */
function stepsIn(run: Run, time: string): Extract<Block, { kind: "steps" }> {
  const last = run.blocks.at(-1);
  if (last?.kind === "steps") {
    return last;
  }
  const block = {
    kind: "steps" as const,
    key: `${run.id}:${run.blocks.length}`,
    calls: [],
    started: time,
    finished: null,
    state: "done" as const,
    latest: false,
  };
  run.blocks.push(block);
  return block;
}

function latestOf(times: string[]): string | null {
  let latest: string | null = null;
  for (const time of times) {
    if (latest === null || Date.parse(time) > Date.parse(latest)) {
      latest = time;
    }
  }
  return latest;
}

function blockTime(block: Block): string {
  switch (block.kind) {
    case "rebuilt":
      return block.time;
    case "steps":
      return block.started;
    default:
      return block.entry.time;
  }
}

/**
 * The activity grouped into runs: each run's request, what its agent said, its tool calls gathered into blocks between
 * those, and how it ended. `working` are the calls still running, and `running` whether the latest run still works;
 * `built` places a rebuild marker in the run it fell in, at that time.
 */
export function runsOf(
  steps: Step[],
  working: Step[],
  running: boolean,
  built: string | null,
): Run[] {
  const live = new Set(working);
  const runs: Run[] = [];
  // The reasoning nothing has followed yet in the latest run, which whatever comes next ends.
  let thinking: Call | null = null;
  // The tool calls being written out, by key, until each is called, which takes its place.
  const writing = new Map<string, { calls: Call[]; call: Call }>();
  for (const step of steps) {
    let run = runs.at(-1);
    if (!run || run.id !== step.entry.run_id) {
      run = {
        id: step.entry.run_id,
        number: runs.length + 1,
        request: null,
        started: step.entry.time,
        ended: null,
        blocks: [],
        calls: [],
      };
      runs.push(run);
    }
    const entry = step.entry;
    if (
      thinking &&
      (thinking.step.entry.run_id !== run.id || entry.kind !== "thought")
    ) {
      // Reasoning a run never came back from stays unfinished.
      if (thinking.step.entry.run_id === run.id) {
        thinking.finished = entry.time;
      }
      thinking = null;
    }
    if (entry.kind === "reasoning" || entry.kind === "thought") {
      if (thinking) {
        // Its summary, which comes once it is done.
        thinking.summary = entry.text;
        thinking.target = headline(entry.text);
        thinking.finished = entry.time;
        thinking = null;
      } else {
        const block = stepsIn(run, entry.time);
        if (entry.kind === "reasoning") {
          thinking = reasoning(step, null);
          block.calls.push(thinking);
        } else {
          // A summary with no start counted for it, which was quick.
          const quick = reasoning(step, entry.text);
          quick.finished = entry.time;
          block.calls.push(quick);
        }
      }
    } else if (entry.kind === "request") {
      run.request = entry;
      run.started = entry.time;
      run.blocks.push({ kind: "message", entry });
    } else if (entry.kind === "steered") {
      run.blocks.push({ kind: "message", entry });
    } else if (entry.kind === "said") {
      run.blocks.push({ kind: "said", entry });
    } else if (entry.kind === "ended") {
      run.ended = entry;
      run.blocks.push({
        kind: "ended",
        entry,
        status: (entry.data.status as ModelStatus | undefined) ?? "done",
      });
    } else if (entry.kind === "composing") {
      const update = composing(step);
      const written = writing.get(update.key);
      if (written) {
        // Still the one row, from when it began, with what it works on once that much is written.
        written.call.size = update.size;
        written.call.target = update.target || written.call.target;
      } else {
        const block = stepsIn(run, entry.time);
        block.calls.push(update);
        writing.set(update.key, { calls: block.calls, call: update });
      }
    } else if (entry.kind === "tool") {
      // A placeholder until the run's end is known, below.
      const placeholder = call(step, live, false);
      const written = writing.get(placeholder.key);
      writing.delete(placeholder.key);
      const at = written ? written.calls.indexOf(written.call) : -1;
      if (written && at !== -1) {
        written.calls[at] = placeholder;
      } else {
        stepsIn(run, entry.time).calls.push(placeholder);
      }
    }
  }

  runs.forEach((run, index) => {
    const next = runs[index + 1];
    // A run that never recorded its end, like one whose process died, is over once another starts.
    const over = run.ended !== null || next !== undefined || !running;
    for (const block of run.blocks) {
      if (block.kind !== "steps") {
        continue;
      }
      block.calls = block.calls.map((placeholder) => {
        switch (placeholder.kind) {
          case "reasoning":
            return { ...placeholder, state: reasoningState(placeholder, over) };
          case "composing":
            return { ...placeholder, state: over ? "unfinished" : "running" };
          case "tool":
            return call(placeholder.step, live, over);
        }
      });
      run.calls.push(...block.calls);
      const states = block.calls.map((each) => each.state);
      block.state = states.includes("failed")
        ? "failed"
        : states.includes("running")
          ? "running"
          : "done";
      block.finished = latestOf(
        block.calls.map((each) => each.finished ?? each.started),
      );
      block.latest = !over && run.blocks.at(-1) === block;
    }
    const rebuilt = built ? Date.parse(built) : NaN;
    const end = run.ended?.time ?? next?.started;
    if (
      built &&
      rebuilt >= Date.parse(run.started) &&
      (end === undefined || rebuilt <= Date.parse(end))
    ) {
      const at = run.blocks.findIndex(
        (block) => Date.parse(blockTime(block)) > rebuilt,
      );
      run.blocks.splice(at === -1 ? run.blocks.length : at, 0, {
        kind: "rebuilt",
        time: built,
      });
    }
  });
  return runs;
}

/** The call a working run is on now, and which of its calls that is, counting from 1. */
export function currentCall(
  run: Run | undefined,
): { call: Call; number: number } | null {
  if (!run) {
    return null;
  }
  for (let index = run.calls.length - 1; index >= 0; index -= 1) {
    if (run.calls[index].state === "running") {
      return { call: run.calls[index], number: index + 1 };
    }
  }
  return null;
}

/**
 * What every session the agents worked in has used of `measure`, as reported at the end of each turn; null before any
 * reported it. Each report is its session's total so far, a resumed session's earlier runs and all, so the latest of
 * each session counts.
 */
function totalUsage(steps: Step[], measure: string): number | null {
  const sessions = new Map<string, number>();
  for (const { entry } of steps) {
    const amount = entry.data[measure];
    if (entry.kind === "usage" && typeof amount === "number") {
      sessions.set(String(entry.data.session_id), amount);
    }
  }
  return sessions.size === 0
    ? null
    : [...sessions.values()].reduce((total, each) => total + each, 0);
}

/** What the sessions have cost, in US dollars, of the agent providers that report it. */
export function totalCost(steps: Step[]): number | null {
  return totalUsage(steps, "cost_usd");
}

/** What the sessions have used in tokens, of the agent providers that report tokens rather than cost. */
export function totalTokens(steps: Step[]): number | null {
  return totalUsage(steps, "tokens");
}
