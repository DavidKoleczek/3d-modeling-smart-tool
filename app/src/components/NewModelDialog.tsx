import { useRef, useState, type FormEvent } from "react";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ModelFields } from "@/components/ModelPicker";
import { AddReferences, ReferenceTiles } from "@/components/References";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { CropMarks } from "@/components/ui/empty-state";
import { Help, Input, Label, Textarea } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { createModel, type ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import { effortLabel, useIntelligence } from "@/lib/intelligence";
import { NAME, shortDirectory, suggestName } from "@/lib/models";
import { takesReferences, useReferences } from "@/lib/references";
import { submitsOnEnter } from "@/lib/utils";

/** Asks the dialog to open, starting from `model` when one is named. */
export type NewModelRequest = { id: number; model?: string };

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
    if (badName) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createModel({
        prompt: prompt.trim(),
        name,
        ...(await references.ready()),
        ...intelligence.choice,
      });
      onCreated(taken?.name ?? name);
      setPrompt("");
      setTypedName(null);
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
                    <Help>
                      {typedName === null && name !== ""
                        ? "Suggested from the description. "
                        : ""}
                      Letters, digits, dots, dashes, and underscores.
                    </Help>
                  )}
                </div>
                <div>
                  <span className="mb-1.5 block text-label">AI model</span>
                  <ModelFields intelligence={intelligence} />
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
                disabled={busy || badName}
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
