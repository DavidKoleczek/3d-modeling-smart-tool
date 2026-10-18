import { useState } from "react";

import { ImageDialog, type ShownImage } from "@/components/ImageDialog";
import { Icon } from "@/components/ui/icon";
import type { ActivityEntry } from "@/lib/api";
import { useModelImage } from "@/lib/images";
import { cn } from "@/lib/utils";

const IMAGE = /\.(png|jpe?g|webp)$/i;

/** Who sent a request or steering message, as the activity names them. */
function sender(origin: string | null): string {
  if (origin === "app") {
    return "You";
  }
  if (origin?.startsWith("claude-code:")) {
    return "Claude Code";
  }
  return origin ?? "Command line";
}

/** A reference image the request gave, read through the host; click it to see it large. */
function ReferenceImage({
  model,
  path,
  onOpen,
}: {
  model: string;
  path: string;
  onOpen: () => void;
}) {
  const { url } = useModelImage(model, path);
  const name = path.replace(/^references\//, "");
  return (
    <button
      type="button"
      disabled={!url}
      onClick={onOpen}
      aria-label={`Open ${name}`}
      title={name}
      className="group/reference relative size-10 overflow-hidden rounded-sm border border-line bg-field hover:border-line-control"
    >
      {url && <img src={url} alt="" className="size-full object-cover" />}
      <span className="absolute inset-0 hidden place-items-center bg-panel/70 text-ink group-hover/reference:grid">
        <Icon name="expand" />
      </span>
    </button>
  );
}

/** What someone asked of the model, or told its agent while it worked, with what they gave it to work from. */
export function Message({
  entry,
  model,
}: {
  entry: ActivityEntry;
  model: string;
}) {
  const steering = entry.kind === "steered";
  const references = (entry.data.references as string[] | undefined) ?? [];
  const images = references.filter((path) => IMAGE.test(path));
  const files = references.filter((path) => !IMAGE.test(path));
  const error = typeof entry.data.error === "string" ? entry.data.error : null;
  const [opened, setOpened] = useState<ShownImage | null>(null);
  return (
    <li className="flex max-w-[86%] shrink-0 flex-col items-end gap-1 self-end">
      <span
        className="text-caption text-ink-muted"
        title={entry.origin ?? undefined}
      >
        {sender(entry.origin)}
        {steering && ", steering"}
      </span>
      <p
        className={cn(
          "rounded-lg border bg-field px-3 py-1.5 wrap-break-word whitespace-pre-wrap",
          steering ? "border-line-control" : "border-line",
        )}
      >
        {entry.text}
      </p>
      {references.length > 0 && (
        <div className="flex flex-wrap items-end justify-end gap-1">
          {images.map((path) => (
            <ReferenceImage
              key={path}
              model={model}
              path={path}
              onOpen={() => setOpened({ path })}
            />
          ))}
          {files.map((path) => (
            <span
              key={path}
              className="rounded-sm border border-line bg-panel px-1.5 py-0.75 mono-annotation whitespace-nowrap text-ink-muted"
            >
              {path.replace(/^references\//, "")}
            </span>
          ))}
        </div>
      )}
      {error && (
        <span className="text-caption text-danger">Not delivered. {error}</span>
      )}
      <ImageDialog
        model={model}
        image={opened}
        onClose={() => setOpened(null)}
      />
    </li>
  );
}
