import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";

import { AddReferences, ReferenceChips } from "@/components/References";
import { ModelMenu } from "@/components/ModelPicker";
import { Button } from "@/components/ui/button";
import { CropMarks } from "@/components/ui/empty-state";
import { Help } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { openAppFolder, type ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import { shortDirectory } from "@/lib/models";
import { takesReferences, useReferences } from "@/lib/references";
import {
  ask,
  MODE_LABELS,
  sessionOf,
  type Handoff,
  type NextRequest,
} from "@/lib/requests";
import { submitsOnEnter } from "@/lib/utils";

const DOLLARS = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const TOKENS = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

function dollars(amount: number): string {
  return amount > 0 && amount < 0.01 ? "<$0.01" : DOLLARS.format(amount);
}

function carriesFiles(event: DragEvent) {
  return event.dataTransfer.types.includes("Files");
}

/**
 * Where the person talks to a model's agent. While a run works, what they write steers it; otherwise it starts a new
 * run on the model in the mode picked, Shape, Rig, Color, or Detail, continuing its last session unless they switch
 * that off. A rig, coloring, or detailing can be sent with nothing written, for the agent to work it out. The AI model they pick runs that next run,
 * so a pick made while one works waits for it.
 */
export function Composer({
  model,
  models,
  next,
  handoff,
  onTaken,
  cost,
  tokens,
}: {
  model: ModelSummary;
  models: ModelSummary[];
  next: NextRequest;
  /** What to put in the message from elsewhere in the app, such as marked views, once it is for this model. */
  handoff: Handoff | null;
  onTaken: (id: number) => void;
  /** What the agents' sessions on the model have cost, in US dollars, once any reported it. */
  cost: number | null;
  /** What the sessions of agent providers that report no cost have used in tokens, once any reported it. */
  tokens: number | null;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const references = useReferences();
  const { addFiles } = references;
  const field = useRef<HTMLTextAreaElement>(null);
  // The handoff last put in, which StrictMode's second run of the effect would otherwise put in twice.
  const taken = useRef(0);

  useEffect(() => {
    if (
      !handoff ||
      handoff.model !== model.name ||
      handoff.id === taken.current
    ) {
      return;
    }
    taken.current = handoff.id;
    setDraft((current) =>
      [current.trim(), handoff.text].filter(Boolean).join("\n\n"),
    );
    addFiles(handoff.files);
    field.current?.focus();
    onTaken(handoff.id);
  }, [handoff, model.name, addFiles, onTaken]);
  const running = model.status === "running";
  const { intelligence } = next;
  const session = sessionOf(model, next);
  // Every mode but shaping has a built model to work out what to do with.
  const unasked = next.mode !== "shape" && !running;
  const sendable = Boolean(draft.trim()) || unasked;

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!sendable || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ask(model, next, text, await references.ready());
      references.clear();
      setDraft("");
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  const openFolder = () => {
    setError(null);
    openAppFolder("model", model.name).catch((cause: unknown) =>
      setError(describe(cause)),
    );
  };

  const files = takesReferences(references);
  const problem = error ?? references.error ?? intelligence.error;
  return (
    <form
      onSubmit={submit}
      {...(running
        ? {}
        : {
            ...files,
            onDragEnter: (event: DragEvent) => setDragging(carriesFiles(event)),
            onDragLeave: (event: DragEvent) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                setDragging(false);
              }
            },
            onDrop: (event: DragEvent) => {
              setDragging(false);
              files.onDrop(event);
            },
          })}
      className="relative shrink-0 border-t border-line bg-panel px-3 pt-2 pb-2.5"
    >
      <div className="rounded-md border border-line-control bg-field py-1.5 pr-1.5 pl-2.5 transition-colors focus-within:border-ink focus-within:bg-panel">
        <div className="mb-1.5 empty:hidden">
          <ReferenceChips references={references} />
        </div>
        <textarea
          ref={field}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={submitsOnEnter(() => void submit())}
          rows={2}
          placeholder={
            running
              ? "Steer the agent, like make the legs longer"
              : unasked && next.mode === "rig"
                ? `Describe what moves on ${model.name} and how, or send to let the agent work it out`
                : unasked && next.mode === "color"
                  ? `Describe the colors ${model.name} should take, or send to let the agent work them out`
                  : unasked
                    ? `Describe the detail to paint on ${model.name}, or send to let the agent work it out`
                    : model.status === null
                      ? `Describe what ${model.name} should be`
                      : `Describe a change to ${model.name}`
          }
          aria-label={running ? "Message to the agent" : "What to change"}
          className="block field-sizing-content max-h-40 min-h-10 w-full resize-none bg-transparent text-ink outline-none placeholder:text-ink-muted focus-visible:outline-none"
        />
        <div className="mt-1.5 flex flex-wrap items-center justify-end gap-1">
          {!running && (
            <div className="mr-auto flex shrink-0 items-center gap-1">
              <AddReferences
                references={references}
                models={models}
                exclude={model.name}
                trigger={
                  <Button
                    size="sm"
                    icon
                    aria-label="Add references"
                    title="Add images, models, or folders to work from; you can also drop or paste them"
                  />
                }
              >
                <Icon name="attach" />
              </AddReferences>
              <span aria-hidden className="mx-1 h-4 w-px bg-line" />
              <Segmented
                label="Mode"
                size="sm"
                value={next.mode}
                onChange={next.onMode}
                options={[
                  { value: "shape", label: MODE_LABELS.shape },
                  {
                    value: "rig",
                    label: MODE_LABELS.rig,
                    disabled: model.built
                      ? undefined
                      : `${model.name} can be rigged once it's built`,
                  },
                  {
                    value: "color",
                    label: MODE_LABELS.color,
                    disabled: model.built
                      ? undefined
                      : `${model.name} can be colored once it's built`,
                  },
                  {
                    value: "detail",
                    label: MODE_LABELS.detail,
                    disabled: model.built
                      ? undefined
                      : `${model.name} can be detailed once it's built`,
                  },
                ]}
              />
              <Switch
                checked={session.continuing}
                onChange={next.onResume}
                disabled={!session.continuable}
                title={session.hint}
              >
                Continue session
              </Switch>
            </div>
          )}
          <div className="flex min-w-0 items-center gap-1">
            <ModelMenu
              intelligence={intelligence}
              hint={
                running
                  ? "Runs the next request; the run working now keeps its own"
                  : "Runs this request"
              }
            />
            <Button
              type="submit"
              variant="primary"
              size="sm"
              icon={!running}
              disabled={busy || !sendable}
              aria-label={running ? "Steer" : "Send"}
            >
              {busy ? <LoadingMark /> : <Icon name="send" />}
              {running && "Steer"}
            </Button>
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex min-w-0 items-center">
        <button
          type="button"
          onClick={openFolder}
          title={`Open ${model.directory}, where the agent works on ${model.name}`}
          className="-ml-1 flex h-5 min-w-0 items-center gap-1.5 rounded-sm px-1 mono-annotation text-ink-muted hover:bg-hover hover:text-ink"
        >
          <Icon name="folder" className="shrink-0" />
          <span className="truncate">{shortDirectory(model.directory)}</span>
          <Icon name="link-out" className="shrink-0" />
        </button>
        {(cost !== null || tokens !== null) && (
          <span
            title={`What the agents' sessions on ${model.name} have used in all, as reported at the end of each turn${running ? ". The turn under way counts once it ends." : "."}`}
            className="ml-auto shrink-0 pl-3 mono-annotation text-ink-muted"
          >
            {[
              cost !== null && dollars(cost),
              tokens !== null && `${TOKENS.format(tokens)} tokens`,
            ]
              .filter(Boolean)
              .join(" + ")}
            {running && " so far"}
          </span>
        )}
      </div>
      {problem && <Help error>{problem}</Help>}
      {dragging && (
        <div className="pointer-events-none absolute inset-1 grid place-items-center rounded-md bg-canvas/95 text-label text-ink">
          <CropMarks />
          Drop images, models, or folders to work from
        </div>
      )}
    </form>
  );
}
