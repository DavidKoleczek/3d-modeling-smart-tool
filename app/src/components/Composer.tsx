import { LoaderCircle, SendHorizontal, Square } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AttachButtons, AttachmentList } from "@/components/Attachments";
import { Button } from "@/components/ui/button";
import {
  cancelModel,
  createModel,
  steerModel,
  type ModelSummary,
} from "@/lib/api";
import { AppError, describe } from "@/lib/errors";
import { takesFiles, useAttachments } from "@/lib/attachments";
import { submitsOnEnter } from "@/lib/utils";

/**
 * Where the person talks to a model's agent. While a run works, what they write steers it and Stop ends it; otherwise
 * it starts a new run on the model, continuing its last session unless they switch that off.
 */
export function Composer({
  model,
  models,
}: {
  model: ModelSummary;
  models: ModelSummary[];
}) {
  const [draft, setDraft] = useState("");
  const [resume, setResume] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attachments = useAttachments();
  const running = model.status === "running";

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (running) {
        await steerModel(model.name, text);
      } else {
        await createModel({
          prompt: text,
          name: model.name,
          resume_session: resume,
          references: attachments.files.map((file) => file.upload),
          reference_models: attachments.models,
        });
        attachments.clear();
      }
      setDraft("");
    } catch (cause) {
      setError(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setError(null);
    try {
      await cancelModel(model.name);
    } catch (cause) {
      // Stopped already, which is what was asked for.
      if (!(cause instanceof AppError && cause.reason === "not-running")) {
        setError(describe(cause));
      }
    }
  };

  const problem = error ?? attachments.error;
  return (
    <form
      onSubmit={submit}
      {...(running ? {} : takesFiles(attachments.addFiles))}
      className="flex flex-col gap-2 border-t p-3"
    >
      {!running && <AttachmentList attachments={attachments} />}
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={submitsOnEnter(() => void submit())}
        rows={2}
        placeholder={
          running ? "Steer it: make the legs longer..." : "Ask for a change..."
        }
        aria-label={running ? "Message to the agent" : "What to change"}
        className="field-sizing-content max-h-40 min-h-14 w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
      <div className="flex items-center gap-2">
        {!running && (
          <>
            <AttachButtons
              attachments={attachments}
              models={models}
              exclude={model.name}
            />
            <label
              className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"
              title={
                resume
                  ? "Continues the agent session that last worked on it, which remembers the conversation"
                  : "Starts a fresh agent session, which reads the model's script"
              }
            >
              <input
                type="checkbox"
                checked={resume}
                onChange={(event) => setResume(event.target.checked)}
              />
              Continue session
            </label>
          </>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {running && (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => void stop()}
            >
              <Square />
              Stop
            </Button>
          )}
          <Button
            type="submit"
            size="icon-sm"
            disabled={busy || !draft.trim()}
            aria-label={running ? "Steer" : "Ask for the change"}
          >
            {busy ? (
              <LoaderCircle className="animate-spin" />
            ) : (
              <SendHorizontal />
            )}
          </Button>
        </span>
      </div>
      {problem && <p className="text-xs text-destructive">{problem}</p>}
    </form>
  );
}
