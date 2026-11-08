import { useEffect, useRef, useState, type RefObject } from "react";

import {
  ConfirmModelChange,
  type Asked,
} from "@/components/ConfirmModelChange";
import { ModelThumb } from "@/components/ModelThumb";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { Notice } from "@/components/ui/notice";
import { StatusMark } from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import type { ModelListing, ModelSummary } from "@/lib/api";
import { referable } from "@/lib/references";
import { matching, renameProblem, shortDirectory } from "@/lib/models";
import { ago } from "@/lib/time";
import { cn, copyText } from "@/lib/utils";

export type Picker = {
  listing: ModelListing | null;
  selected: string | null;
  onSelect: (name: string) => void;
  onNew: () => void;
};

/** Your models: every model in the app's directory, newest first, to search, pick from, rename, and delete. */
export function ModelList({
  listing,
  selected,
  onSelect,
  onNew,
  error,
  search,
  onWorkFrom,
  onRename,
  onDelete,
}: Picker & {
  error: string | null;
  search?: RefObject<HTMLInputElement | null>;
  /** Starts a new model from the one named. */
  onWorkFrom: (name: string) => void;
  /** Each resolves once done, and rejects with what refused it. */
  onRename: (name: string, newName: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  // The id of the model whose name is being edited, which a rename from elsewhere keeps.
  const [editing, setEditing] = useState<string | null>(null);
  // The change being confirmed, kept while its dialog closes so it does not empty as it goes.
  const [asked, setAsked] = useState<Asked | null>(null);
  const [asking, setAsking] = useState(false);
  // Set as soon as a rename is asked for, ahead of the render that opens its dialog and takes the focus.
  const confirming = useRef(false);
  // The model to edit the name of once its menu has closed and given the focus back.
  const opening = useRef<string | null>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const models = matching(listing, query);
  const workable = new Set(
    referable(listing?.models ?? []).map((model) => model.name),
  );
  const problems = [...(error ? [error] : []), ...(listing?.unreadable ?? [])];

  const ask = (change: Asked) => {
    confirming.current = change.kind === "rename";
    setAsked(change);
    setAsking(true);
  };
  const closeAsking = () => {
    confirming.current = false;
    setAsking(false);
  };
  const confirm = async (change: Asked) => {
    if (change.kind === "rename") {
      await onRename(change.model.name, change.newName);
      setEditing(null);
    } else {
      const all = listing?.models ?? [];
      const index = all.findIndex((model) => model.id === change.model.id);
      const neighbor = all[index + 1] ?? all[index - 1];
      await onDelete(change.model.name);
      if (change.model.name === selected && neighbor) {
        onSelect(neighbor.name);
      }
    }
    closeAsking();
  };

  return (
    <nav
      aria-label="Your models"
      className="flex h-full min-h-0 flex-col bg-panel"
    >
      <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line pr-1.5 pl-3 text-label">
        <h2>Your models</h2>
        {listing && (
          <span className="mono-annotation text-ink-muted">
            {listing.models.length}
          </span>
        )}
        <Tooltip content="New model" keys="N">
          <Button
            size="sm"
            icon
            aria-label="New model"
            onClick={onNew}
            className="ml-auto"
          >
            <Icon name="add" />
          </Button>
        </Tooltip>
      </header>
      <label className="m-2 flex h-6 shrink-0 items-center gap-1.5 rounded-sm border border-line-control bg-field pr-1 pl-2 text-ink-muted focus-within:border-ink focus-within:bg-panel">
        <Icon name="search" />
        <input
          ref={search}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setQuery("");
              event.currentTarget.blur();
            }
          }}
          placeholder="Search models"
          aria-label="Search models"
          className="min-w-0 flex-1 bg-transparent text-label font-normal text-ink outline-none placeholder:text-ink-muted [&::-webkit-search-cancel-button]:hidden"
        />
        {!query && <Kbd>/</Kbd>}
      </label>
      {problems.length > 0 && (
        <ul className="flex shrink-0 flex-col gap-1 px-2 pb-2">
          {problems.map((problem) => (
            <li key={problem}>
              <Notice>{problem}</Notice>
            </li>
          ))}
        </ul>
      )}
      <ol className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto px-1 pb-1">
        {listing && listing.models.length > 0 && models.length === 0 && (
          <li className="px-3 py-2 text-ink-muted">
            No models match {query.trim()}.
          </li>
        )}
        {models.map((model) => (
          <li key={model.id} className="group/row relative">
            {editing === model.id ? (
              <NameEditor
                model={model}
                models={listing?.models ?? []}
                inputRef={nameInput}
                onAsk={(newName) => ask({ kind: "rename", model, newName })}
                onLeave={() => {
                  if (!confirming.current) {
                    setEditing(null);
                  }
                }}
              />
            ) : (
              <button
                type="button"
                onClick={() => onSelect(model.name)}
                aria-current={model.name === selected ? "true" : undefined}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2.5 rounded-sm py-1.5 pr-9 pl-2 text-left -outline-offset-2",
                  model.name === selected ? "bg-accent-soft" : "hover:bg-hover",
                )}
              >
                <ModelThumb model={model} />
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate font-medium">{model.name}</span>
                  <span className="flex min-w-0 items-center gap-1.5">
                    {model.status !== "done" && (
                      <StatusMark
                        status={model.status}
                        since={model.last_run?.started}
                      />
                    )}
                    {model.status !== "running" && (
                      <span className="truncate mono-annotation text-ink-muted">
                        {ago(model.updated)}
                      </span>
                    )}
                  </span>
                </span>
              </button>
            )}
            {editing !== model.id && (
              <div className="absolute top-1/2 right-1.5 -translate-y-1/2 opacity-0 group-focus-within/row:opacity-100 group-hover/row:opacity-100 has-data-popup-open:opacity-100">
                <Menu
                  onOpenChangeComplete={(open) => {
                    if (!open && opening.current === model.id) {
                      opening.current = null;
                      setEditing(model.id);
                    }
                  }}
                >
                  <MenuTrigger
                    render={
                      <Button
                        size="sm"
                        icon
                        aria-label={`More for ${model.name}`}
                      />
                    }
                  >
                    <Icon name="more" />
                  </MenuTrigger>
                  <MenuContent align="end">
                    <MenuItem onClick={() => void copyText(model.name)}>
                      <Icon name="copy" className="text-ink-muted" />
                      Copy name
                    </MenuItem>
                    {workable.has(model.name) && (
                      <MenuItem onClick={() => onWorkFrom(model.name)}>
                        <Icon name="model" className="text-ink-muted" />
                        Use in a new model
                      </MenuItem>
                    )}
                    <MenuSeparator />
                    <MenuItem
                      disabled={model.status === "running"}
                      onClick={() => {
                        opening.current = model.id;
                      }}
                    >
                      <Icon name="rename" className="text-ink-muted" />
                      <span className="flex-1">Rename</span>
                      {model.status === "running" && (
                        <span className="pl-3 text-caption">Stop it first</span>
                      )}
                    </MenuItem>
                    <MenuItem
                      onClick={() => ask({ kind: "delete", model })}
                      className="text-danger"
                    >
                      <Icon name="delete" />
                      Delete
                    </MenuItem>
                  </MenuContent>
                </Menu>
              </div>
            )}
          </li>
        ))}
      </ol>
      {listing && (
        <footer
          title={listing.directory}
          className="shrink-0 truncate border-t border-line px-3 py-2 mono-annotation text-ink-muted"
        >
          {shortDirectory(listing.directory)}
        </footer>
      )}
      <ConfirmModelChange
        asked={asked}
        open={asking}
        onConfirm={confirm}
        onClose={closeAsking}
        finalFocus={asked?.kind === "rename" ? nameInput : undefined}
      />
    </nav>
  );
}

/**
 * A model's name being edited in its row, checked as it is typed. Enter asks to rename it to what was typed, and
 * Escape or leaving the field ends editing with nothing changed.
 */
function NameEditor({
  model,
  models,
  inputRef,
  onAsk,
  onLeave,
}: {
  model: ModelSummary;
  models: ModelSummary[];
  inputRef: RefObject<HTMLInputElement | null>;
  onAsk: (newName: string) => void;
  onLeave: () => void;
}) {
  const [value, setValue] = useState(model.name);
  const name = value.trim();
  const problem = renameProblem(name, model.name, models);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [inputRef]);

  return (
    <div className="flex min-w-0 items-start gap-2.5 rounded-sm bg-accent-soft px-2 py-1.5">
      <ModelThumb model={model} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onLeave();
            } else if (event.key === "Enter") {
              event.preventDefault();
              if (name === model.name) {
                onLeave();
              } else if (!problem) {
                onAsk(name);
              }
            }
          }}
          onBlur={onLeave}
          aria-label={`New name for ${model.name}`}
          aria-invalid={problem ? true : undefined}
          spellCheck={false}
          className={cn(
            "h-6 min-w-0 rounded-sm border bg-field px-1.5 font-medium text-ink outline-none focus:bg-panel",
            problem ? "border-danger" : "border-line-control focus:border-ink",
          )}
        />
        {problem ? (
          <span role="alert" className="text-caption text-danger">
            {problem}
          </span>
        ) : (
          <span className="text-caption text-ink-muted">
            Enter to rename, Esc to cancel
          </span>
        )}
      </div>
    </div>
  );
}
