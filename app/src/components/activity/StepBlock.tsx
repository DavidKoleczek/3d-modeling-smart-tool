import { useState } from "react";

import { CallDetail, ReasoningDetail } from "@/components/activity/CallDetail";
import { ImageDialog, type ShownImage } from "@/components/ImageDialog";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import type { ModelSummary } from "@/lib/api";
import type { Call } from "@/lib/runs";
import { between, useElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";

function Running({ since }: { since: string }) {
  return <>{useElapsed(since)}</>;
}

/** How much of a call the agent has written out so far, in its characters. */
function sizeOf(characters: number): string {
  return characters < 1024
    ? `${characters} chars`
    : `${(characters / 1024).toFixed(1)} KB`;
}

/** Whether `path` is an image of the model the app can show: one of its renders or of what it was given. */
function showable(model: ModelSummary, path: string): boolean {
  return (
    model.files.includes(path) ||
    model.references.some(
      (reference) =>
        reference === path ||
        (reference.endsWith("/") && path.startsWith(reference)),
    )
  );
}

/**
 * One step: a plain verb, what it worked on, and how long it took; the running one counts up. A tool call opens to the
 * call in full, and reasoning to its summary. An image the agent looked at opens large.
 */
function ToolRow({
  call,
  model,
  open,
  onToggle,
  onOpen,
}: {
  call: Call;
  model: ModelSummary;
  open: boolean;
  onToggle: () => void;
  onOpen: (image: ShownImage) => void;
}) {
  const running = call.state === "running";
  const failed = call.state === "failed";
  const image = call.icon === "image" && showable(model, call.target);
  const verb = running ? call.doing : call.verb;
  const expandable = call.kind === "tool" || call.summary !== null;
  const writing = call.kind === "composing" && running;
  return (
    <li className="border-t border-line first:border-t-0">
      <div
        className={cn(
          "relative flex min-h-7 min-w-0 items-center gap-2 px-2",
          running && "bg-accent-soft",
        )}
      >
        {/* Under the row's content, so the whole row opens the step while an image's name still opens the image. */}
        {expandable && (
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${verb} ${call.target}`.trim()}
            title={call.target}
            onClick={onToggle}
            className="absolute inset-0 -outline-offset-2 hover:bg-hover"
          />
        )}
        <Icon
          name={failed ? "warning" : call.icon}
          className={cn(
            "pointer-events-none relative",
            failed
              ? "text-danger"
              : running
                ? "text-accent-ink"
                : "text-ink-muted",
          )}
        />
        <span
          className={cn(
            "pointer-events-none relative shrink-0 text-label",
            failed && "text-danger",
          )}
        >
          {verb}
        </span>
        {image ? (
          <span className="relative min-w-0 flex-1 truncate">
            <button
              type="button"
              onClick={() =>
                onOpen({ path: call.target, version: model.built })
              }
              title={`Open ${call.target}`}
              className="max-w-full truncate text-left mono-value text-ink-muted underline decoration-line-control underline-offset-2 hover:text-ink hover:decoration-ink"
            >
              {call.target}
            </button>
          </span>
        ) : (
          <span
            className={cn(
              "pointer-events-none relative min-w-0 flex-1 truncate text-ink-muted",
              call.kind === "reasoning" ? "text-label" : "mono-value",
            )}
          >
            {call.target}
          </span>
        )}
        <span
          className={cn(
            "pointer-events-none relative flex shrink-0 items-center gap-1.5 mono-annotation",
            running ? "text-accent-ink" : "text-ink-muted",
          )}
        >
          {writing && call.size !== null && <span>{sizeOf(call.size)}</span>}
          {running && <LoadingMark />}
          {running ? (
            <Running since={call.started} />
          ) : (
            call.finished && between(call.started, call.finished)
          )}
          <Icon
            name="chevron"
            className={cn(
              "text-ink-faint transition-transform",
              !open && "-rotate-90",
              !expandable && "invisible",
            )}
          />
        </span>
      </div>
      {open && call.summary !== null ? (
        <ReasoningDetail summary={call.summary} />
      ) : open && call.kind === "tool" ? (
        <CallDetail model={model.name} call={call} />
      ) : (
        call.error && (
          <p className="px-2 pb-2 pl-8 mono-value font-normal wrap-break-word whitespace-pre-wrap text-danger">
            {call.error}
          </p>
        )
      )}
    </li>
  );
}

/**
 * Consecutive tool calls between two messages: how many, how long, and whether they are still going. A call that
 * failed shows only on its own row, since the agent often goes on past one.
 */
export function StepBlock({
  model,
  calls,
  started,
  finished,
  state,
  open,
  onToggle,
}: {
  model: ModelSummary;
  calls: Call[];
  started: string;
  finished: string | null;
  state: "running" | "done" | "failed";
  open: boolean;
  onToggle: () => void;
}) {
  const [opened, setOpened] = useState<ShownImage | null>(null);
  const [shown, setShown] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) =>
    setShown((keys) => {
      const next = new Set(keys);
      if (!next.delete(key)) {
        next.add(key);
      }
      return next;
    });
  return (
    <li className="shrink-0 overflow-hidden rounded-md border border-line bg-panel">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex h-7 w-full items-center gap-1.5 px-2 text-left text-label -outline-offset-2 hover:bg-hover"
      >
        <Icon
          name="chevron"
          className={cn(
            "text-ink-muted transition-transform",
            !open && "-rotate-90",
          )}
        />
        {calls.length} {calls.length === 1 ? "step" : "steps"}
        <span className="mono-annotation text-ink-muted">
          {state === "running" ? (
            <Running since={started} />
          ) : (
            between(started, finished ?? started)
          )}
        </span>
        <span className="flex-1" />
        {state === "done" && !open && <Icon name="check" />}
        {state === "running" && !open && <LoadingMark />}
      </button>
      {open && (
        <ol className="border-t border-line">
          {calls.map((call) => (
            <ToolRow
              key={call.key}
              call={call}
              model={model}
              open={shown.has(call.key)}
              onToggle={() => toggle(call.key)}
              onOpen={setOpened}
            />
          ))}
        </ol>
      )}
      <ImageDialog
        model={model.name}
        image={opened}
        onClose={() => setOpened(null)}
      />
    </li>
  );
}
