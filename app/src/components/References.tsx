import { useState } from "react";

import { HeldImageDialog, type HeldImage } from "@/components/ImageDialog";
import { ModelThumb } from "@/components/ModelThumb";
import { Help } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import type { ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import { pinnedKeys, togglePinOf, useLibrary } from "@/lib/library";
import { sourceOf, type Reference, type References } from "@/lib/references";
import { counted } from "@/lib/stats";
import { cn } from "@/lib/utils";

function sending(reference: Reference): boolean {
  return (
    reference.kind !== "model" &&
    !reference.error &&
    reference.sent < reference.bytes
  );
}

/** How far along a reference is, or what it holds: a percentage while it is sent, then a folder's count of files. */
function detail(reference: Reference): string | null {
  if (reference.error) {
    return "Didn't arrive";
  }
  if (sending(reference)) {
    return `${Math.floor((reference.sent / reference.bytes) * 100)}%`;
  }
  return reference.kind === "folder"
    ? counted(reference.files, "file", "files")
    : null;
}

/** What hovering a reference tells: what went wrong, or what a folder left out. */
function explanation(reference: Reference): string {
  if (reference.error) {
    return `${reference.name}: ${reference.error}`;
  }
  if (reference.skipped.length > 0) {
    return `${reference.name}, leaving out ${reference.skipped.join(", ")}`;
  }
  return reference.name;
}

const ICONS = { file: "file", folder: "folder", model: "model" } as const;

function Progress({ reference }: { reference: Reference }) {
  if (!sending(reference)) {
    return null;
  }
  return (
    <span
      aria-hidden
      className="absolute bottom-0 left-0 h-0.5 bg-accent transition-[width]"
      style={{ width: `${(reference.sent / reference.bytes) * 100}%` }}
    />
  );
}

function ReferenceIcon({ reference }: { reference: Reference }) {
  if (reference.preview) {
    return (
      <img
        src={reference.preview}
        alt=""
        className="size-4.5 rounded-[2px] object-cover"
      />
    );
  }
  return <Icon name={ICONS[reference.kind]} className="text-ink-muted" />;
}

/** What a request will work from, in a row of chips, each of which can be taken off again; an image opens large. */
export function ReferenceChips({ references }: { references: References }) {
  const [opened, setOpened] = useState<HeldImage | null>(null);
  if (references.items.length === 0) {
    return null;
  }
  return (
    <>
      <ul className="flex flex-wrap gap-1">
        {references.items.map((reference) => {
          const preview = reference.preview;
          const label = (
            <>
              <ReferenceIcon reference={reference} />
              <span className="max-w-32 truncate">{reference.name}</span>
            </>
          );
          return (
            <li
              key={reference.key}
              title={explanation(reference)}
              className={cn(
                "relative flex h-6 max-w-full items-center gap-1 overflow-hidden rounded-sm border bg-panel pr-0.5 pl-1 text-label",
                reference.error ? "border-danger text-danger" : "border-line",
              )}
            >
              {preview ? (
                <button
                  type="button"
                  aria-label={`See ${reference.name} large`}
                  onClick={() =>
                    setOpened({ name: reference.name, url: preview })
                  }
                  className="flex min-w-0 cursor-zoom-in items-center gap-1 rounded-sm"
                >
                  {label}
                </button>
              ) : (
                label
              )}
              {detail(reference) && (
                <span className="mono-annotation text-ink-muted">
                  {detail(reference)}
                </span>
              )}
              <button
                type="button"
                aria-label={`Remove ${reference.name}`}
                onClick={() => references.remove(reference.key)}
                className="grid size-4.5 place-items-center rounded-sm text-ink-muted hover:bg-hover hover:text-ink"
              >
                <Icon name="close" />
              </button>
              <Progress reference={reference} />
            </li>
          );
        })}
      </ul>
      <HeldImageDialog image={opened} onClose={() => setOpened(null)} />
    </>
  );
}

/** What a new model will work from, as a row of tiles with a picture of each, each of which can be pinned or taken off. */
export function ReferenceTray({
  references,
  models,
}: {
  references: References;
  models: ModelSummary[];
}) {
  const { library } = useLibrary();
  const [opened, setOpened] = useState<HeldImage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (references.items.length === 0) {
    return (
      <p className="rounded-sm border border-dashed border-line-control p-3 text-center text-caption text-ink-muted">
        Nothing yet. Pick from the library, or drop or paste images, models, and
        folders anywhere here.
      </p>
    );
  }
  const byName = new Map(models.map((model) => [model.name, model]));
  const pinned = pinnedKeys(library, models);

  const togglePin = (reference: Reference) => {
    setProblem(null);
    togglePinOf(reference, models).then(
      (kept) => kept && references.tag(reference.key, kept),
      (cause: unknown) => setProblem(describe(cause)),
    );
  };

  return (
    <>
      <ul className="flex flex-wrap gap-2">
        {references.items.map((reference) => {
          const model =
            reference.kind === "model" ? byName.get(reference.name) : undefined;
          const preview = reference.preview;
          const isPinned = pinned.has(sourceOf(reference));
          return (
            <li
              key={reference.key}
              title={explanation(reference)}
              className="group/ref relative w-18 min-w-0"
            >
              <div
                className={cn(
                  "relative size-18 overflow-hidden rounded-sm border bg-field",
                  reference.error ? "border-danger" : "border-line",
                )}
              >
                {preview ? (
                  <button
                    type="button"
                    aria-label={`See ${reference.name} large`}
                    onClick={() =>
                      setOpened({ name: reference.name, url: preview })
                    }
                    className="block size-full cursor-zoom-in"
                  >
                    <img
                      src={preview}
                      alt=""
                      className="size-full object-cover"
                    />
                  </button>
                ) : model ? (
                  <ModelThumb model={model} size="fill" />
                ) : (
                  <span className="grid size-full place-items-center text-ink-muted">
                    <Icon name={ICONS[reference.kind]} size={24} />
                  </span>
                )}
                <Progress reference={reference} />
              </div>
              <p
                className={cn(
                  "mt-1 flex min-w-0 items-center gap-1 mono-annotation",
                  reference.error ? "text-danger" : "text-ink-muted",
                )}
              >
                <span className="truncate">{reference.name}</span>
                {detail(reference) && (
                  <span className="ml-auto shrink-0">{detail(reference)}</span>
                )}
              </p>
              {!reference.error && !sending(reference) && (
                <button
                  type="button"
                  aria-pressed={isPinned}
                  aria-label={
                    isPinned
                      ? `Unpin ${reference.name}`
                      : `Pin ${reference.name}`
                  }
                  title={isPinned ? "Unpin" : "Pin, to find it in Pinned"}
                  onClick={() => togglePin(reference)}
                  className={cn(
                    "shadow-sm absolute top-1 left-1 grid size-5 place-items-center rounded-sm bg-panel/90 hover:text-ink",
                    isPinned
                      ? "text-accent-ink"
                      : "text-ink-muted opacity-0 group-focus-within/ref:opacity-100 group-hover/ref:opacity-100",
                  )}
                >
                  <Icon name={isPinned ? "pinned" : "pin"} />
                </button>
              )}
              <button
                type="button"
                aria-label={`Remove ${reference.name}`}
                title="Remove"
                onClick={() => references.remove(reference.key)}
                className="shadow-sm absolute top-1 right-1 grid size-5 place-items-center rounded-sm bg-panel/90 text-ink-muted hover:text-ink"
              >
                <Icon name="close" />
              </button>
            </li>
          );
        })}
      </ul>
      {problem && <Help error>{problem}</Help>}
      <HeldImageDialog image={opened} onClose={() => setOpened(null)} />
    </>
  );
}
