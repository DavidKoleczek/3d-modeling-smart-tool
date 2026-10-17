import {
  Check,
  FilePen,
  FileText,
  FolderSearch,
  LoaderCircle,
  SquareTerminal,
  TriangleAlert,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Composer } from "@/components/Composer";
import { StatusBadge } from "@/components/StatusBadge";
import { useActivity, type Step } from "@/lib/activity";
import {
  readModelFile,
  type ActivityEntry,
  type ModelStatus,
  type ModelSummary,
} from "@/lib/api";
import { duration } from "@/lib/time";
import { cn } from "@/lib/utils";

const IMAGE = /\.(png|jpe?g|webp)$/i;
const TOOL_ICONS: Record<string, LucideIcon> = {
  Bash: SquareTerminal,
  Read: FileText,
  Edit: FilePen,
  Write: FilePen,
  Glob: FolderSearch,
  Grep: FolderSearch,
};

/** Who sent a request or steering message, as the activity names them. */
function sender(origin: string | null): string {
  if (origin === "app") {
    return "You";
  }
  if (origin?.startsWith("claude-code:")) {
    return "Claude Code";
  }
  return origin ?? "Command line";
}

/** A reference image the request gave, read through the host. */
function ReferenceImage({ model, path }: { model: string; path: string }) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    readModelFile(model, path).then(
      (file) => {
        if (current) {
          setSource(`data:${file.mimeType};base64,${file.base64}`);
        }
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [model, path]);

  return source ? (
    <img
      src={source}
      alt={path}
      title={path}
      className="size-14 rounded-lg border object-cover"
    />
  ) : (
    <span className="size-14 rounded-lg border bg-muted" title={path} />
  );
}

function References({ model, paths }: { model: string; paths: string[] }) {
  const files = paths.filter((path) => !IMAGE.test(path));
  return (
    <div className="flex flex-wrap items-end justify-end gap-1.5">
      {paths
        .filter((path) => IMAGE.test(path))
        .map((path) => (
          <ReferenceImage key={path} model={model} path={path} />
        ))}
      {files.map((path) => (
        <span
          key={path}
          className="rounded-md border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
        >
          {path.replace(/^references\//, "")}
        </span>
      ))}
    </div>
  );
}

/** What someone asked of the model, or told its agent while it worked. */
function Message({ entry, model }: { entry: ActivityEntry; model: string }) {
  const steering = entry.kind === "steered";
  const references = (entry.data.references as string[] | undefined) ?? [];
  const error = typeof entry.data.error === "string" ? entry.data.error : null;
  let label = sender(entry.origin);
  if (steering) {
    label += ", steering";
  } else if (entry.data.resumed) {
    label += ", continuing its session";
  }
  return (
    <li className="flex max-w-[85%] flex-col items-end gap-1 self-end">
      <span
        className="text-xs text-muted-foreground"
        title={entry.origin ?? undefined}
      >
        {label}
      </span>
      <p
        className={cn(
          "rounded-xl px-3 py-2 text-sm wrap-break-word whitespace-pre-wrap",
          entry.origin === "app"
            ? "bg-primary text-primary-foreground"
            : "bg-secondary text-secondary-foreground",
          steering && "border border-primary/30",
        )}
      >
        {entry.text}
      </p>
      {references.length > 0 && <References model={model} paths={references} />}
      {error && (
        <span className="text-xs text-destructive">Not delivered: {error}</span>
      )}
    </li>
  );
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000));
  return (
    <span className="flex items-center gap-1 text-primary">
      <LoaderCircle className="size-3.5 animate-spin" />
      {duration(seconds)}
    </span>
  );
}

/** A tool call the agent made: what it works on, and whether it is running, done, or failed. */
function Tool({ step, working }: { step: Step; working: boolean }) {
  const name = String(step.entry.data.name ?? "");
  const Icon = TOOL_ICONS[name] ?? Wrench;
  const failed = step.result?.data.failed === true;
  let state = null;
  if (working) {
    state = <Elapsed since={step.entry.time} />;
  } else if (failed) {
    state = <X className="size-3.5 text-destructive" />;
  } else if (step.result) {
    state = <Check className="size-3.5" />;
  }
  return (
    <li className="flex flex-col gap-0.5 px-1 text-xs text-muted-foreground">
      <span className="flex min-w-0 items-center gap-1.5">
        <Icon className="size-3.5 shrink-0" />
        <span className="shrink-0 font-medium text-foreground">{name}</span>
        <span className="min-w-0 truncate font-mono" title={step.entry.text}>
          {step.entry.text}
        </span>
        <span className="ml-auto shrink-0">{state}</span>
      </span>
      {failed && step.result?.text && (
        <span className="pl-5 wrap-break-word text-destructive">
          {step.result.text}
        </span>
      )}
    </li>
  );
}

/** How a run ended; its final words are already in what the agent said. */
function Ended({ entry }: { entry: ActivityEntry }) {
  const error = typeof entry.data.error === "string" ? entry.data.error : null;
  return (
    <li className="flex flex-col items-center gap-1 py-1 text-center text-xs">
      <StatusBadge status={entry.data.status as ModelStatus} />
      {error && (
        <span className="wrap-break-word text-destructive">{error}</span>
      )}
    </li>
  );
}

function Entry({
  step,
  model,
  working,
}: {
  step: Step;
  model: string;
  working: boolean;
}) {
  switch (step.entry.kind) {
    case "request":
    case "steered":
      return <Message entry={step.entry} model={model} />;
    case "said":
      return (
        <li className="max-w-[85%] self-start rounded-xl bg-muted px-3 py-2 text-sm wrap-break-word whitespace-pre-wrap">
          {step.entry.text}
        </li>
      );
    case "tool":
      return <Tool step={step} working={working} />;
    case "ended":
      return <Ended entry={step.entry} />;
    default:
      return null;
  }
}

/** The model in view's activity: what was asked of it and by whom, what its agent did, and where to talk to it. */
export function ActivityPanel({
  model,
  models,
}: {
  model: ModelSummary | null;
  models: ModelSummary[];
}) {
  const {
    steps,
    model: read,
    working,
    error,
  } = useActivity(model?.name ?? null);
  const shown = read ?? model;
  const list = useRef<HTMLOListElement>(null);
  // Follows what comes in while the person is at the bottom, and stays put while they read further up.
  const pinned = useRef(true);

  useEffect(() => {
    if (pinned.current && list.current) {
      list.current.scrollTop = list.current.scrollHeight;
    }
  }, [steps.length, shown?.name]);

  let empty: string | null = null;
  if (shown === null) {
    empty = "Pick a model to follow its work, or start one with New model.";
  } else if (read === null && error === null) {
    empty = "Reading what has been done...";
  } else if (steps.length === 0 && error === null) {
    empty = "Nothing has been asked of it yet.";
  }

  return (
    <section className="flex min-h-0 flex-col rounded-xl border bg-card">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <h2 className="min-w-0 truncate text-sm font-medium">
          {shown?.name ?? "Activity"}
        </h2>
        {shown && <StatusBadge status={shown.status} />}
      </header>
      <ol
        ref={list}
        onScroll={(event) => {
          const element = event.currentTarget;
          pinned.current =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            48;
        }}
        className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3"
      >
        {error && (
          <li className="flex gap-1.5 text-xs text-destructive">
            <TriangleAlert className="mt-px size-3.5 shrink-0" />
            <span className="min-w-0 wrap-break-word">{error}</span>
          </li>
        )}
        {empty && (
          <li className="m-auto text-center text-sm text-muted-foreground">
            {empty}
          </li>
        )}
        {shown &&
          // Only ever appended to, and read again from the start for another model, so a step keeps its index.
          steps.map((step, index) => (
            <Entry
              key={index}
              step={step}
              model={shown.name}
              working={working.includes(step)}
            />
          ))}
      </ol>
      {shown && <Composer key={shown.name} model={shown} models={models} />}
    </section>
  );
}
