import { Box, Plus, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  firstRender,
  readModelFile,
  type ModelListing,
  type ModelSummary,
} from "@/lib/api";
import { ago } from "@/lib/time";
import { cn } from "@/lib/utils";

type Picker = {
  listing: ModelListing | null;
  selected: string | null;
  onSelect: (name: string) => void;
  onNew: () => void;
  creating: boolean;
  className?: string;
};

/** A model's first render, read again each time the model is rebuilt. */
function Thumbnail({ model }: { model: ModelSummary }) {
  const render = firstRender(model);
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    if (!render) {
      return;
    }
    let current = true;
    readModelFile(model.name, render).then(
      (file) => {
        if (current) {
          setSource(`data:${file.mimeType};base64,${file.base64}`);
        }
      },
      () => {
        if (current) {
          setSource(null);
        }
      },
    );
    return () => {
      current = false;
    };
  }, [model.name, model.built, render]);

  return (
    <span className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-muted">
      {source && render ? (
        <img src={source} alt="" className="size-full object-cover" />
      ) : (
        <Box className="size-5 text-muted-foreground" />
      )}
    </span>
  );
}

/** Every model in the app's directory, newest first; picking one shows it. */
export function ModelList({
  listing,
  selected,
  onSelect,
  onNew,
  creating,
  error,
  className,
}: Picker & { error: string | null }) {
  return (
    <section
      className={cn(
        "flex min-h-0 flex-col rounded-xl border bg-card",
        className,
      )}
    >
      <header className="border-b px-4 py-3">
        <h2 className="text-sm font-medium">Models</h2>
        <p
          className="truncate text-xs text-muted-foreground"
          title={listing?.directory}
        >
          {listing?.directory ?? "Looking for models..."}
        </p>
      </header>
      {(error || (listing?.unreadable.length ?? 0) > 0) && (
        <ul className="flex flex-col gap-1 border-b p-3 text-xs text-destructive">
          {[...(error ? [error] : []), ...(listing?.unreadable ?? [])].map(
            (problem) => (
              <li key={problem} className="flex gap-1.5">
                <TriangleAlert className="mt-px size-3.5 shrink-0" />
                <span className="min-w-0 wrap-break-word">{problem}</span>
              </li>
            ),
          )}
        </ul>
      )}
      <ol className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
        <li>
          <button
            type="button"
            onClick={onNew}
            aria-current={creating}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg p-2 text-left text-sm font-medium text-primary outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
              creating && "bg-muted",
            )}
          >
            <span className="flex size-12 shrink-0 items-center justify-center rounded-lg border border-dashed border-primary/40">
              <Plus className="size-5" />
            </span>
            New model
          </button>
        </li>
        {listing?.models.length === 0 && (
          <li className="m-auto p-2 text-center text-sm text-muted-foreground">
            No models here yet. Start one with New model, or ask your agent.
          </li>
        )}
        {listing?.models.map((model) => (
          <li key={model.name}>
            <button
              type="button"
              onClick={() => onSelect(model.name)}
              aria-current={model.name === selected}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg p-2 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
                model.name === selected && "bg-muted",
              )}
            >
              <Thumbnail model={model} />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="truncate text-sm font-medium">
                  {model.name}
                </span>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <StatusBadge status={model.status} />
                  <span className="truncate">{ago(model.updated)}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The model list as a menu, where there is no room for the list. */
export function ModelMenu({
  listing,
  selected,
  onSelect,
  onNew,
  creating,
  className,
}: Picker) {
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      <Button
        type="button"
        variant={creating ? "secondary" : "outline"}
        size="sm"
        onClick={onNew}
      >
        <Plus />
        New model
      </Button>
      {listing && listing.models.length > 0 && (
        <select
          aria-label="Model"
          title={listing.directory}
          value={selected ?? ""}
          onChange={(event) => onSelect(event.target.value)}
          className="h-8 max-w-48 min-w-0 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {selected === null && (
            <option value="" disabled>
              Pick a model
            </option>
          )}
          {listing.models.map((model) => (
            <option key={model.name} value={model.name}>
              {model.name}
            </option>
          ))}
        </select>
      )}
    </span>
  );
}
