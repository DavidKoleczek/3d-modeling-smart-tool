import { useState, type RefObject } from "react";

import { ModelThumb } from "@/components/ModelThumb";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { Notice } from "@/components/ui/notice";
import { StatusMark } from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import type { ModelListing } from "@/lib/api";
import { referable } from "@/lib/references";
import { matching, shortDirectory } from "@/lib/models";
import { ago } from "@/lib/time";
import { cn, copyText } from "@/lib/utils";

export type Picker = {
  listing: ModelListing | null;
  selected: string | null;
  onSelect: (name: string) => void;
  onNew: () => void;
};

/** Your models: every model in the app's directory, newest first, to search and pick from. */
export function ModelList({
  listing,
  selected,
  onSelect,
  onNew,
  error,
  search,
  onWorkFrom,
}: Picker & {
  error: string | null;
  search?: RefObject<HTMLInputElement | null>;
  /** Starts a new model from the one named. */
  onWorkFrom: (name: string) => void;
}) {
  const [query, setQuery] = useState("");
  const models = matching(listing, query);
  const workable = new Set(
    referable(listing?.models ?? []).map((model) => model.name),
  );
  const problems = [...(error ? [error] : []), ...(listing?.unreadable ?? [])];

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
          <li key={model.name} className="group/row relative">
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
            <div className="absolute top-1/2 right-1.5 -translate-y-1/2 opacity-0 group-focus-within/row:opacity-100 group-hover/row:opacity-100 has-data-popup-open:opacity-100">
              <Menu>
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
                </MenuContent>
              </Menu>
            </div>
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
    </nav>
  );
}
