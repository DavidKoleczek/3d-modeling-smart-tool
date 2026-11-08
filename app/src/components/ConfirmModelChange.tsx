import { useRef, useState, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Notice } from "@/components/ui/notice";
import type { ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";

/** A change to a model the person confirms first, since it moves or removes the model's folder. */
export type Asked =
  | { kind: "rename"; model: ModelSummary; newName: string }
  | { kind: "delete"; model: ModelSummary };

/** Where a model's folder goes once it is renamed: beside where it is. */
function renamedDirectory(model: ModelSummary, newName: string): string {
  return model.directory.slice(0, -model.name.length) + newName;
}

/** Asks before renaming or deleting a model, saying what goes with it, and shows what refused it. */
export function ConfirmModelChange({
  asked,
  open,
  onConfirm,
  onClose,
  finalFocus,
}: {
  asked: Asked | null;
  open: boolean;
  /** Resolves once the change is made, and rejects with what refused it. */
  onConfirm: (asked: Asked) => Promise<void>;
  onClose: () => void;
  finalFocus?: RefObject<HTMLElement | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  if (asked === null) {
    return null;
  }
  const { model } = asked;
  const deleting = asked.kind === "delete";
  // Deleting stops the run working on the model first.
  const stopping = deleting && model.status === "running";

  const confirm = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await onConfirm(asked);
    } catch (cause) {
      setFailure(describe(cause));
    } finally {
      setBusy(false);
    }
  };

  let action = deleting ? "Delete" : "Rename";
  if (stopping) {
    action = "Stop and delete";
  }
  let doing = deleting ? "Deleting..." : "Renaming...";
  if (stopping) {
    doing = "Stopping and deleting...";
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(opened) => {
        // A change under way finishes either way, so the dialog stays to say how it went.
        if (!opened && !busy) {
          setFailure(null);
          onClose();
        }
      }}
    >
      <DialogContent
        title={
          deleting
            ? `Delete ${model.name}?`
            : `Rename ${model.name} to ${asked.newName}?`
        }
        initialFocus={deleting ? cancel : undefined}
        finalFocus={finalFocus}
        className="sm:max-w-110"
      >
        <div className="flex flex-col gap-3 px-5 py-4 text-body">
          {deleting ? (
            <p>
              This deletes its folder and everything in it: its model.py,
              model.glb, renders, references, checks, and agent sessions. It
              can't be undone.
            </p>
          ) : (
            <>
              <p>
                Its folder moves to{" "}
                <span className="mono-annotation break-all">
                  {renamedDirectory(model, asked.newName)}
                </span>
                . The app, your pins, and an agent continuing its session follow
                it there.
              </p>
              <p className="text-ink-muted">
                Anything else that points at its old folder, such as a project
                that loads its model.glb, needs changing by hand.
              </p>
            </>
          )}
          {stopping && (
            <Notice tone="neutral" icon="stop">
              An agent is working on it. Deleting stops it first.
            </Notice>
          )}
          {failure && <Notice>{failure}</Notice>}
        </div>
        <DialogFooter>
          <span className="flex-1" />
          <Button
            ref={cancel}
            variant="secondary"
            size="lg"
            disabled={busy}
            onClick={() => {
              setFailure(null);
              onClose();
            }}
          >
            Cancel
          </Button>
          <Button
            variant={deleting ? "danger" : "primary"}
            size="lg"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {busy && <LoadingMark />}
            {busy ? doing : action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
