import { useRef, type ReactElement, type ReactNode } from "react";

import { ModelThumb } from "@/components/ModelThumb";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import type { ModelSummary } from "@/lib/api";
import { referable, type Reference, type References } from "@/lib/references";
import { counted } from "@/lib/stats";
import { cn } from "@/lib/utils";

/**
 * The menu that adds what a request works from: files, a folder, or one of the models here. `trigger` is the button
 * that opens it, holding `children`.
 */
export function AddReferences({
  references,
  models,
  exclude,
  trigger,
  children,
}: {
  references: References;
  models: ModelSummary[];
  exclude?: string;
  trigger: ReactElement;
  children: ReactNode;
}) {
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const choices = referable(models).filter(
    (model) =>
      model.name !== exclude && !references.models.includes(model.name),
  );

  return (
    <>
      <input
        ref={files}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? []);
          event.target.value = "";
          references.addFiles(picked);
        }}
      />
      <input
        ref={folder}
        type="file"
        hidden
        {...{ webkitdirectory: "" }}
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? []);
          event.target.value = "";
          references.addFolder(picked);
        }}
      />
      <Menu>
        <MenuTrigger render={trigger}>{children}</MenuTrigger>
        <MenuContent className="max-h-(--available-height) overflow-y-auto">
          <MenuItem onClick={() => files.current?.click()}>
            <Icon name="file" className="text-ink-muted" />
            Files...
          </MenuItem>
          <MenuItem onClick={() => folder.current?.click()}>
            <Icon name="folder" className="text-ink-muted" />
            Folder...
          </MenuItem>
          {choices.length > 0 && (
            <>
              <MenuSeparator />
              <MenuGroup>
                <MenuGroupLabel>Models here</MenuGroupLabel>
                {choices.map((model) => (
                  <MenuItem
                    key={model.name}
                    onClick={() => references.addModel(model.name)}
                  >
                    <ModelThumb model={model} size={20} />
                    {model.name}
                  </MenuItem>
                ))}
              </MenuGroup>
            </>
          )}
        </MenuContent>
      </Menu>
    </>
  );
}

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

/** What a request will work from, in a row of chips, each of which can be taken off again. */
export function ReferenceChips({ references }: { references: References }) {
  if (references.items.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {references.items.map((reference) => (
        <li
          key={reference.key}
          title={explanation(reference)}
          className={cn(
            "relative flex h-6 max-w-full items-center gap-1 overflow-hidden rounded-sm border bg-panel pr-0.5 pl-1 text-label",
            reference.error ? "border-danger text-danger" : "border-line",
          )}
        >
          <ReferenceIcon reference={reference} />
          <span className="max-w-32 truncate">{reference.name}</span>
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
      ))}
    </ul>
  );
}

/** What a new model will work from, as tiles with a picture of each, each of which can be taken off again. */
export function ReferenceTiles({
  references,
  models,
}: {
  references: References;
  models: ModelSummary[];
}) {
  if (references.items.length === 0) {
    return null;
  }
  const byName = new Map(models.map((model) => [model.name, model]));
  return (
    <ul className="grid grid-cols-2 gap-2">
      {references.items.map((reference) => {
        const model =
          reference.kind === "model" ? byName.get(reference.name) : undefined;
        return (
          <li
            key={reference.key}
            title={explanation(reference)}
            className="relative min-w-0"
          >
            <div
              className={cn(
                "relative h-22 overflow-hidden rounded-sm border bg-field",
                reference.error ? "border-danger" : "border-line",
              )}
            >
              {reference.preview ? (
                <img
                  src={reference.preview}
                  alt=""
                  className="size-full object-cover"
                />
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
              {reference.kind === "model" && <Icon name="model" />}
              <span className="truncate">{reference.name}</span>
              {detail(reference) && (
                <span className="ml-auto shrink-0">{detail(reference)}</span>
              )}
            </p>
            <Button
              variant="secondary"
              size="sm"
              icon
              aria-label={`Remove ${reference.name}`}
              onClick={() => references.remove(reference.key)}
              className="absolute top-1 right-1"
            >
              <Icon name="close" />
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
