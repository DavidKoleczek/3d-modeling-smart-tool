import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ModelFields } from "@/components/ModelPicker";
import { AddReferences, ReferenceTiles } from "@/components/References";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { CropMarks } from "@/components/ui/empty-state";
import { Help, Input, Label, Textarea } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { createModel, type ModelRequest, type ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import { effortLabel, useIntelligence } from "@/lib/intelligence";
import { NAME, shortDirectory, suggestName } from "@/lib/models";
import { takesReferences, useReferences } from "@/lib/references";
import { cn, submitsOnEnter } from "@/lib/utils";

/** Asks the dialog to open, starting from `model` when one is named. */
export type NewModelRequest = { id: number; model?: string };

/** The budgets as typed, each empty for none. */
type TypedBudgets = {
  triangles: string;
  drawCalls: string;
  smallest: string;
  largest: string;
};

type Budgets = Pick<
  ModelRequest,
  "max_triangles" | "max_draw_calls" | "screen_size"
>;

const NO_BUDGETS: TypedBudgets = {
  triangles: "",
  drawCalls: "",
  smallest: "",
  largest: "",
};
const WHOLE = /^[1-9]\d*$/;
const NONE = /^none$/i;

/** One budget as typed: a number, null for none, undefined when empty, or false when it is none of those. */
function budgetOf(typed: string): number | null | undefined | false {
  const field = typed.trim();
  if (field === "") {
    return undefined;
  }
  if (NONE.test(field)) {
    return null;
  }
  return WHOLE.test(field) ? Number(field) : false;
}

/** The budgets typed, as a request takes them, or what is wrong with them. Empty ones are left out of the request. */
function checkBudgets(typed: TypedBudgets): Budgets | string {
  const parsed = [
    typed.triangles,
    typed.drawCalls,
    typed.smallest,
    typed.largest,
  ].map(budgetOf);
  if (parsed.some((budget) => budget === false)) {
    return "Budgets are whole numbers of 1 or more, or none.";
  }
  const [triangles, drawCalls, smallest, largest] = parsed as (
    number | null | undefined
  )[];
  let screen: [number, number] | null | undefined;
  if (smallest === null || largest === null) {
    if (typeof smallest === "number" || typeof largest === "number") {
      return "Give both sizes on screen, or none.";
    }
    screen = null;
  } else if (smallest !== undefined && largest !== undefined) {
    if (smallest > largest) {
      return "Give the smallest size on screen first.";
    }
    screen = [smallest, largest];
  } else if (smallest !== largest) {
    return "Give both sizes on screen, or neither.";
  }
  return {
    ...(triangles !== undefined ? { max_triangles: triangles } : {}),
    ...(drawCalls !== undefined ? { max_draw_calls: drawCalls } : {}),
    ...(screen !== undefined ? { screen_size: screen } : {}),
  };
}

/** What an empty budget field stands for: the default for a new model, and the model's own budget for a change. */
function keptBudget(changing: boolean, budget: number | null | undefined) {
  if (!changing) {
    return "default";
  }
  return budget == null ? "none" : String(budget);
}

/**
 * Starts a new model over the workspace, so a model being built stays in view behind it: what to build, its name, the
 * AI model, and the files, folders, and models to work from. Closing it keeps the draft until the app reloads.
 */
export function NewModelDialog({
  open,
  onOpenChange,
  request,
  models,
  directory,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: NewModelRequest;
  models: ModelSummary[];
  directory: string | null;
  onCreated: (name: string) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [typedName, setTypedName] = useState<string | null>(null);
  const [typedBudgets, setTypedBudgets] = useState(NO_BUDGETS);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [handled, setHandled] = useState(request.id);
  const references = useReferences();
  const intelligence = useIntelligence();
  const described = useRef<HTMLTextAreaElement>(null);

  // A request to start from a model adds it once, when it arrives.
  if (request.id !== handled) {
    setHandled(request.id);
    if (request.model) {
      references.addModel(request.model);
    }
  }

  const name = typedName ?? (prompt.trim() ? suggestName(prompt, models) : "");
  const badName = name !== "" && !NAME.test(name);
  // Ignoring case, as the directory does on Windows and macOS.
  const taken = models.find(
    (model) => model.name.toLowerCase() === name.toLowerCase(),
  );
  const budgets = checkBudgets(typedBudgets);
  const badBudgets = typeof budgets === "string";
  // Kept open while a budget is wrong, so what is wrong stays in view.
  const showAdvanced = advanced || badBudgets;
  // A budget left empty keeps the one the model has, so those are what the empty fields show.
  const kept = taken?.last_run;
  const changing = Boolean(kept);
  const typeBudget =
    (field: keyof TypedBudgets) => (event: ChangeEvent<HTMLInputElement>) =>
      setTypedBudgets({ ...typedBudgets, [field]: event.target.value });
  const count = references.items.length;

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (busy) {
      return;
    }
    if (!prompt.trim()) {
      setMissing(true);
      described.current?.focus();
      return;
    }
    if (badName || typeof budgets === "string") {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createModel({
        prompt: prompt.trim(),
        name,
        ...budgets,
        ...(await references.ready()),
        ...intelligence.choice,
      });
      onCreated(taken?.name ?? name);
      setPrompt("");
      setTypedName(null);
      setTypedBudgets(NO_BUDGETS);
      references.clear();
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  const problem = error ?? references.error ?? intelligence.error;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New model"
        subtitle={directory ? `In ${shortDirectory(directory)}` : undefined}
        initialFocus={described}
        keepMounted
        className="sm:max-w-190"
      >
        <ErrorBoundary what="New model" className="p-5">
          <form
            onSubmit={submit}
            {...takesReferences(references)}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="grid min-h-0 flex-1 overflow-y-auto sm:grid-cols-[300px_minmax(0,1fr)]">
              <div className="order-last border-line bg-canvas p-5 max-sm:border-t sm:order-0 sm:border-r">
                <div className="relative flex h-full min-h-60 flex-col gap-3 p-4">
                  <CropMarks />
                  <span className="text-label">References</span>
                  <ReferenceTiles references={references} models={models} />
                  <span className="flex-1" />
                  <p className="text-center text-caption text-ink-muted">
                    Drop or paste images, models, and folders here
                  </p>
                  <div className="flex justify-center">
                    <AddReferences
                      references={references}
                      models={models}
                      trigger={<Button variant="secondary" size="sm" />}
                    >
                      <Icon name="add" />
                      Add references
                      <Icon name="chevron" className="text-ink-muted" />
                    </AddReferences>
                  </div>
                </div>
              </div>
              <div className="flex flex-col gap-4 p-5">
                <div>
                  <Label htmlFor="new-model-prompt">Describe it</Label>
                  <Textarea
                    ref={described}
                    id="new-model-prompt"
                    value={prompt}
                    onChange={(event) => {
                      setPrompt(event.target.value);
                      setMissing(false);
                    }}
                    onKeyDown={(event) =>
                      submitsOnEnter(() => void submit())(event)
                    }
                    rows={5}
                    placeholder="A low poly brown bear, standing on all fours"
                    aria-invalid={missing}
                    className="min-h-27 resize-y"
                  />
                  {missing && (
                    <Help error>Describe the model you want built.</Help>
                  )}
                </div>
                <div>
                  <Label htmlFor="new-model-name">Name</Label>
                  <Input
                    id="new-model-name"
                    value={name}
                    onChange={(event) => setTypedName(event.target.value)}
                    placeholder="bear"
                    aria-invalid={badName}
                    className="mono-value"
                  />
                  {badName ? (
                    <Help error>
                      Use letters, digits, dots, dashes, and underscores,
                      starting with a letter or digit.
                    </Help>
                  ) : taken ? (
                    <Help>
                      {taken.name} already exists, so this changes it, in a
                      fresh agent session.
                    </Help>
                  ) : (
                    typedName === null &&
                    name !== "" && <Help>Suggested from the description.</Help>
                  )}
                </div>
                <div>
                  <span className="mb-1.5 block text-label">AI model</span>
                  <ModelFields intelligence={intelligence} />
                </div>
                <div>
                  <button
                    type="button"
                    aria-expanded={showAdvanced}
                    aria-controls="new-model-advanced"
                    onClick={() => setAdvanced(!showAdvanced)}
                    className="flex h-7 items-center gap-1.5 text-label text-ink"
                  >
                    <Icon
                      name="chevron"
                      className={cn(
                        "text-ink-muted transition-transform",
                        !showAdvanced && "-rotate-90",
                      )}
                    />
                    Advanced
                  </button>
                  {showAdvanced && (
                    <fieldset id="new-model-advanced" className="mt-2">
                      <legend className="mb-1.5 block text-label">
                        Budgets
                      </legend>
                      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.6fr)] gap-2">
                        <div>
                          <Label
                            htmlFor="new-model-triangles"
                            className="text-caption text-ink-muted"
                          >
                            Triangles
                          </Label>
                          <Input
                            id="new-model-triangles"
                            value={typedBudgets.triangles}
                            onChange={typeBudget("triangles")}
                            inputMode="numeric"
                            placeholder={keptBudget(
                              changing,
                              kept?.max_triangles,
                            )}
                            aria-invalid={badBudgets}
                            className="mono-value"
                          />
                        </div>
                        <div>
                          <Label
                            htmlFor="new-model-draw-calls"
                            className="text-caption text-ink-muted"
                          >
                            Draw calls
                          </Label>
                          <Input
                            id="new-model-draw-calls"
                            value={typedBudgets.drawCalls}
                            onChange={typeBudget("drawCalls")}
                            inputMode="numeric"
                            placeholder={keptBudget(
                              changing,
                              kept?.max_draw_calls,
                            )}
                            aria-invalid={badBudgets}
                            className="mono-value"
                          />
                        </div>
                        <div>
                          <Label
                            htmlFor="new-model-smallest"
                            className="text-caption text-ink-muted"
                          >
                            On screen, pixels at 1080p
                          </Label>
                          <div className="flex items-center gap-1.5">
                            <Input
                              id="new-model-smallest"
                              value={typedBudgets.smallest}
                              onChange={typeBudget("smallest")}
                              inputMode="numeric"
                              placeholder={keptBudget(
                                changing,
                                kept?.screen_size?.[0],
                              )}
                              aria-label="Smallest on screen"
                              aria-invalid={badBudgets}
                              className="mono-value"
                            />
                            <span className="text-caption text-ink-muted">
                              to
                            </span>
                            <Input
                              value={typedBudgets.largest}
                              onChange={typeBudget("largest")}
                              inputMode="numeric"
                              placeholder={keptBudget(
                                changing,
                                kept?.screen_size?.[1],
                              )}
                              aria-label="Largest on screen"
                              aria-invalid={badBudgets}
                              className="mono-value"
                            />
                          </div>
                        </div>
                      </div>
                      {typeof budgets === "string" ? (
                        <Help error>{budgets}</Help>
                      ) : (
                        <Help>
                          {changing
                            ? `Empty keeps ${taken?.name}'s budget.`
                            : "Empty uses the default."}{" "}
                          Type none for no budget.
                        </Help>
                      )}
                    </fieldset>
                  )}
                </div>
                {problem && <Help error>{problem}</Help>}
              </div>
            </div>
            <DialogFooter>
              <span className="mono-annotation text-ink-muted max-sm:hidden">
                {count} {count === 1 ? "reference" : "references"}
                {intelligence.choice &&
                  ` · ${intelligence.label(intelligence.choice.model)} · ${effortLabel(intelligence.choice.reasoning_effort).toLowerCase()}`}
              </span>
              <span className="flex-1" />
              <Button
                variant="secondary"
                size="lg"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                disabled={busy || badName || badBudgets}
              >
                {busy && <LoadingMark />}
                {busy
                  ? references.uploading
                    ? "Uploading..."
                    : "Starting..."
                  : taken
                    ? `Change ${taken.name}`
                    : "Create model"}
              </Button>
            </DialogFooter>
          </form>
        </ErrorBoundary>
      </DialogContent>
    </Dialog>
  );
}
