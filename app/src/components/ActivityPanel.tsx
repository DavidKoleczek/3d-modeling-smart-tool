import { Fragment, useEffect, useRef, useState } from "react";

import { LiveStrip } from "@/components/activity/LiveStrip";
import { Message } from "@/components/activity/Message";
import { RunDivider } from "@/components/activity/RunDivider";
import { RunResult } from "@/components/activity/RunResult";
import { StepBlock } from "@/components/activity/StepBlock";
import { Composer } from "@/components/Composer";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Markdown } from "@/components/ui/markdown";
import { Notice } from "@/components/ui/notice";
import { useActivity } from "@/lib/activity";
import { cancelModel, type ModelSummary } from "@/lib/api";
import { AppError, describe } from "@/lib/errors";
import { useIntelligence } from "@/lib/intelligence";
import { currentCall, runsOf, totalCost } from "@/lib/runs";
import { statusLabel } from "@/lib/status";
import { updateSettings, useSettings } from "@/lib/settings";
import { timeOfDay } from "@/lib/time";

// How close to the bottom still counts as at it, so new entries keep it scrolled down.
const PINNED_PX = 48;

/**
 * The model in view's activity, run by run: what was asked of it and by whom, what its agent said and did, and how
 * each run ended. While it works, the live strip keeps the current step and Stop in view.
 */
export function ActivityPanel({
  model,
  models,
  liveOnly = false,
}: {
  model: ModelSummary | null;
  models: ModelSummary[];
  /** Only the live strip, under the model where there is room for one pane alone. */
  liveOnly?: boolean;
}) {
  const {
    steps,
    model: read,
    working,
    error,
  } = useActivity(model?.name ?? null);
  const intelligence = useIntelligence();
  const { settings } = useSettings();
  const shown = read ?? model;
  const runs = runsOf(
    steps,
    working,
    shown?.status === "running",
    shown?.built ?? null,
  );
  const latest = runs.at(-1);
  // Blocks the person opened or closed themselves in this model's activity, which keep that until they change it again.
  const toggled = (shown && settings.steps[shown.id]) || {};
  const toggle = (key: string, open: boolean) => {
    if (shown) {
      updateSettings((current) => ({
        ...current,
        steps: {
          ...current.steps,
          [shown.id]: { ...current.steps[shown.id], [key]: open },
        },
      }));
    }
  };
  const [stopError, setStopError] = useState<string | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const pinned = useRef(true);
  // How many steps there were when the person scrolled up, so what came after shows Jump to latest.
  const [readUpTo, setReadUpTo] = useState<number | null>(null);

  useEffect(() => {
    if (pinned.current && list.current) {
      list.current.scrollTop = list.current.scrollHeight;
    }
  }, [steps.length, shown?.name, working.length]);

  const stop = async () => {
    if (!shown) {
      return;
    }
    setStopError(null);
    try {
      await cancelModel(shown.name);
    } catch (cause) {
      // Stopped already, which is what was asked for.
      if (!(cause instanceof AppError && cause.reason === "not-running")) {
        setStopError(describe(cause));
      }
    }
  };

  const jumpToLatest = () => {
    if (list.current) {
      list.current.scrollTo({
        top: list.current.scrollHeight,
        behavior: "smooth",
      });
    }
  };

  let empty: string | null = null;
  if (shown === null) {
    empty = "Pick a model to follow its work, or start one with New model.";
  } else if (read === null && error === null) {
    empty = "Reading what has been done...";
  } else if (steps.length === 0 && error === null) {
    empty = "Nothing has been asked of it yet.";
  }
  const crashed =
    shown?.status === "crashed" && latest !== undefined && !latest.ended;
  const unseen = readUpTo !== null && steps.length > readUpTo;
  const live = shown?.status === "running" && (
    <LiveStrip
      since={latest?.started ?? shown.last_run?.started ?? shown.updated}
      current={currentCall(latest)}
      onStop={() => void stop()}
    />
  );

  if (liveOnly) {
    return live || null;
  }

  return (
    <aside
      aria-label="Activity"
      className="flex h-full min-h-0 flex-col bg-panel"
    >
      <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-3 text-label">
        <h2>Activity</h2>
        {runs.length > 0 && (
          <span className="mono-annotation text-ink-muted">
            {runs.length} {runs.length === 1 ? "run" : "runs"}
          </span>
        )}
      </header>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ol
          ref={list}
          onScroll={(event) => {
            const element = event.currentTarget;
            pinned.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <
              PINNED_PX;
            setReadUpTo(pinned.current ? null : (readUpTo ?? steps.length));
          }}
          className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3"
        >
          {error && (
            <li className="shrink-0">
              <Notice>{error}</Notice>
            </li>
          )}
          {empty && (
            <li className="m-auto text-center text-ink-muted">{empty}</li>
          )}
          {shown &&
            runs.map((run) => (
              <Fragment key={run.id}>
                <RunDivider run={run} intelligence={intelligence} />
                {run.blocks.map((block, index) => {
                  switch (block.kind) {
                    case "message":
                      return (
                        <Message
                          key={index}
                          entry={block.entry}
                          model={shown.name}
                        />
                      );
                    case "said":
                      return (
                        <li key={index} className="shrink-0">
                          <Markdown>{block.entry.text}</Markdown>
                        </li>
                      );
                    case "steps": {
                      const open = toggled[block.key] ?? block.latest;
                      return (
                        <StepBlock
                          key={block.key}
                          model={shown}
                          calls={block.calls}
                          started={block.started}
                          finished={block.finished}
                          state={block.state}
                          open={open}
                          onToggle={() => toggle(block.key, !open)}
                        />
                      );
                    }
                    case "rebuilt":
                      return (
                        <li
                          key={`rebuilt-${index}`}
                          className="flex shrink-0 items-center gap-1.5 mono-annotation text-ink-muted"
                        >
                          <Icon name="check" />
                          Rebuilt {timeOfDay(block.time, true)}
                        </li>
                      );
                    case "ended":
                      return (
                        <RunResult
                          key={index}
                          status={block.status}
                          started={run.started}
                          ended={block.entry.time}
                          error={
                            typeof block.entry.data.error === "string"
                              ? block.entry.data.error
                              : null
                          }
                          files={
                            (block.entry.data.files as string[] | undefined) ??
                            []
                          }
                        />
                      );
                  }
                })}
              </Fragment>
            ))}
          {crashed && latest && (
            <RunResult
              status="crashed"
              started={latest.started}
              ended={null}
              error={null}
              files={[]}
            />
          )}
        </ol>
        {unseen && (
          <Button
            variant="secondary"
            size="sm"
            onClick={jumpToLatest}
            className="absolute bottom-2.5 left-1/2 -translate-x-1/2 shadow-popover"
          >
            <Icon name="arrow-down" />
            Jump to latest
          </Button>
        )}
      </div>
      {live}
      {stopError && <Notice className="mx-3 mt-2 shrink-0">{stopError}</Notice>}
      {shown && (
        <Composer
          key={shown.name}
          model={shown}
          models={models}
          intelligence={intelligence}
          cost={totalCost(steps)}
        />
      )}
      <p role="status" className="sr-only">
        {shown ? `${shown.name}: ${statusLabel(shown.status)}` : ""}
      </p>
    </aside>
  );
}
