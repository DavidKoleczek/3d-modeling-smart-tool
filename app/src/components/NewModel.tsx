import { LoaderCircle, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AttachButtons, AttachmentList } from "@/components/Attachments";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createModel, type ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import { takesFiles, useAttachments } from "@/lib/attachments";
import { submitsOnEnter } from "@/lib/utils";

// `NAME_PATTERN` in create.py.
const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const FILLER = new Set(
  "a an and the of with like in on for to from make me create build model 3d please this that it".split(
    " ",
  ),
);

/** A name for what `prompt` describes, from its first words, that no model in the directory has yet. */
function suggestName(prompt: string, models: ModelSummary[]): string {
  const words = prompt.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  const telling = words.filter((word) => !FILLER.has(word));
  const base =
    (telling.length > 0 ? telling : words).slice(0, 3).join("-").slice(0, 40) ||
    "model";
  // Ignoring case, as the directory does on Windows and macOS.
  const taken = new Set(models.map((model) => model.name.toLowerCase()));
  let name = base;
  for (let suffix = 2; taken.has(name); suffix += 1) {
    name = `${base}-${suffix}`;
  }
  return name;
}

/** The form that starts a new model: what to build, its name, and what to work from. */
export function NewModel({
  models,
  onCreated,
  onCancel,
}: {
  models: ModelSummary[];
  onCreated: (name: string) => void;
  onCancel: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [typedName, setTypedName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attachments = useAttachments();
  const name = typedName ?? (prompt.trim() ? suggestName(prompt, models) : "");
  const badName = name !== "" && !NAME.test(name);
  // Ignoring case, as the directory does on Windows and macOS.
  const taken = models.find(
    (model) => model.name.toLowerCase() === name.toLowerCase(),
  );
  const ready = prompt.trim() !== "" && name !== "" && !badName && !busy;

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!ready) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createModel({
        prompt: prompt.trim(),
        name,
        references: attachments.files.map((file) => file.upload),
        reference_models: attachments.models,
      });
      onCreated(taken?.name ?? name);
    } catch (cause) {
      setError(describe(cause));
      setBusy(false);
    }
  };

  const problem = error ?? attachments.error;
  return (
    <form
      onSubmit={submit}
      {...takesFiles(attachments.addFiles)}
      className="flex min-h-0 flex-col rounded-xl border bg-card"
    >
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <h2 className="text-sm font-medium">New model</h2>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Cancel the new model"
          onClick={onCancel}
          className="ml-auto"
        >
          <X />
        </Button>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        <label className="flex flex-col gap-1 text-xs font-medium">
          What to build
          <textarea
            autoFocus
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={submitsOnEnter(() => void submit())}
            rows={4}
            placeholder="A low poly brown bear, standing on all fours..."
            className="min-h-24 w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm font-normal outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium">
          Name
          <Input
            value={name}
            onChange={(event) => setTypedName(event.target.value)}
            placeholder="bear"
            aria-invalid={badName}
            className="font-normal"
          />
          {badName && (
            <span className="font-normal text-destructive">
              Use letters, digits, ".", "_", and "-", starting with a letter or
              digit.
            </span>
          )}
          {taken && (
            <span className="font-normal text-muted-foreground">
              There's already a model named {taken.name}, so this asks for a
              change to it, in a fresh agent session.
            </span>
          )}
        </label>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium">Work from</span>
          <AttachmentList attachments={attachments} />
          <AttachButtons attachments={attachments} models={models} />
          <span className="text-xs text-muted-foreground">
            Images or models, by the clip, or dropped or pasted here.
          </span>
        </div>
        {problem && <p className="text-xs text-destructive">{problem}</p>}
      </div>
      <footer className="flex justify-end gap-2 border-t p-3">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!ready}>
          {busy && <LoaderCircle className="animate-spin" />}
          {busy ? "Starting..." : taken ? `Change ${taken.name}` : "Create"}
        </Button>
      </footer>
    </form>
  );
}
