import {
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GROUP_LABEL } from "@/components/ui/popup";
import type { ModelMode, ModelSummary } from "@/lib/api";
import {
  isPinnedPrompt,
  pinPrompt,
  unpinPrompt,
  useLibrary,
} from "@/lib/library";
import { pinnedPrompts, recentPrompts, type CannedPrompt } from "@/lib/prompts";
import { cn } from "@/lib/utils";

function moveFocus(event: KeyboardEvent<HTMLElement>) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
    return;
  }
  const rows = Array.from(
    event.currentTarget.querySelectorAll<HTMLElement>("[data-prompt]"),
  );
  const at = rows.indexOf(document.activeElement as HTMLElement);
  const next = event.key === "ArrowDown" ? at + 1 : at - 1;
  if (next >= 0 && next < rows.length) {
    event.preventDefault();
    rows[next].focus();
  }
}

/** Put `text` in `field` in place of what is there, with the cursor at its end. */
function putIn(field: RefObject<HTMLTextAreaElement | null>, text: string) {
  requestAnimationFrame(() => {
    field.current?.focus();
    field.current?.setSelectionRange(text.length, text.length);
  });
}

/**
 * The prompts in `mode` to start from, in a dropdown: the ones the person pinned and what the models here were last
 * asked, each of which can be pinned or unpinned. Picking one puts it in `field` in place of what is written.
 */
export function PromptPicker({
  mode,
  field,
  written,
  models,
  onPick,
  trigger,
  children,
}: {
  mode: ModelMode;
  field: RefObject<HTMLTextAreaElement | null>;
  written: string;
  models: ModelSummary[];
  onPick: (text: string) => void;
  trigger: ReactElement;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { library } = useLibrary();
  const needle = query.trim().toLowerCase();
  const offered = (prompt: CannedPrompt) =>
    prompt.mode === mode &&
    (!needle || prompt.text.toLowerCase().includes(needle));
  const groups = [
    { label: "Pinned", prompts: pinnedPrompts(library, mode).filter(offered) },
    {
      label: "Asked here before",
      prompts: recentPrompts(models).filter(offered),
    },
  ].filter((group) => group.prompts.length > 0);
  const first = groups[0]?.prompts[0];
  const writtenPinned = isPinnedPrompt(library, written, mode);

  const pick = (prompt: CannedPrompt) => {
    onPick(prompt.text);
    setOpen(false);
    setQuery("");
    putIn(field, prompt.text);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={trigger}>{children}</PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        label="Prompts"
        finalFocus={field}
        className="flex max-h-[min(28rem,var(--available-height))] w-[min(26rem,calc(100vw-1rem))] flex-col p-0"
      >
        <div className="border-b border-line p-1.5">
          <label className="flex h-7 items-center gap-1.5 rounded-sm border border-line-control bg-field pr-1 pl-2 text-ink-muted focus-within:border-ink focus-within:bg-panel">
            <Icon name="search" />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && first) {
                  event.preventDefault();
                  pick(first);
                }
              }}
              placeholder="Find a prompt"
              aria-label="Find a prompt"
              className="min-w-0 flex-1 bg-transparent text-label font-normal text-ink outline-none placeholder:text-ink-muted [&::-webkit-search-cancel-button]:hidden"
            />
          </label>
        </div>
        <div
          onKeyDown={moveFocus}
          className="min-h-0 flex-1 overflow-y-auto p-1"
        >
          {groups.length === 0 && (
            <p className="px-2 py-4 text-center text-caption text-ink-muted">
              {needle
                ? `No prompt matches ${query.trim()}.`
                : "No prompts yet. Pin one to find it here."}
            </p>
          )}
          {groups.map((group) => (
            <section key={group.label} className="mb-1 last:mb-0">
              <h3 className={GROUP_LABEL}>{group.label}</h3>
              <ul className="flex flex-col gap-px">
                {group.prompts.map((prompt) => {
                  const isPinned = isPinnedPrompt(
                    library,
                    prompt.text,
                    prompt.mode,
                  );
                  return (
                    <li key={prompt.key} className="group/prompt relative">
                      <button
                        type="button"
                        data-prompt
                        onClick={() => pick(prompt)}
                        title={prompt.text}
                        className="flex w-full min-w-0 items-start gap-2 rounded-sm py-1.5 pr-8 pl-2 text-left text-label -outline-offset-2 hover:bg-hover focus-visible:bg-hover"
                      >
                        <span className="line-clamp-2 min-w-0 flex-1 font-normal">
                          {prompt.text}
                        </span>
                        {prompt.model && (
                          <span className="mt-px shrink-0 mono-annotation text-ink-muted">
                            {prompt.model}
                          </span>
                        )}
                      </button>
                      <Button
                        size="sm"
                        icon
                        aria-pressed={isPinned}
                        aria-label={isPinned ? "Unpin prompt" : "Pin prompt"}
                        title={isPinned ? "Unpin" : "Pin"}
                        onClick={() =>
                          isPinned
                            ? unpinPrompt(prompt.text, prompt.mode)
                            : pinPrompt(prompt.text, prompt.mode)
                        }
                        className={cn(
                          "absolute top-1 right-1",
                          isPinned
                            ? "text-accent-ink"
                            : "text-ink-muted opacity-0 group-focus-within/prompt:opacity-100 group-hover/prompt:opacity-100",
                        )}
                      >
                        <Icon name={isPinned ? "pinned" : "pin"} />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        <footer className="flex justify-end border-t border-line p-1.5">
          <Button
            size="sm"
            disabled={!written.trim() || writtenPinned}
            onClick={() => pinPrompt(written, mode)}
          >
            <Icon name="pin" className="text-ink-muted" />
            Pin what's written
          </Button>
        </footer>
      </PopoverContent>
    </Popover>
  );
}

/**
 * The prompts the person pinned in `mode`, as buttons that put one in `field` in place of what is written, and one
 * that pins or unpins what is written.
 */
export function PinnedPrompts({
  mode,
  field,
  written,
  onPick,
}: {
  mode: ModelMode;
  field: RefObject<HTMLTextAreaElement | null>;
  written: string;
  onPick: (text: string) => void;
}) {
  const { library } = useLibrary();
  const pinned = pinnedPrompts(library, mode);
  const writtenPinned = isPinnedPrompt(library, written, mode);
  return (
    <ul className="mt-2 flex flex-wrap items-center gap-1.5">
      {pinned.map((prompt) => {
        const current = prompt.text === written.trim();
        return (
          <li
            key={prompt.key}
            className={cn(
              "group/chip flex h-6 max-w-72 min-w-0 items-center rounded-sm border transition-colors",
              current
                ? "border-accent-ink bg-accent-soft"
                : "border-line bg-panel hover:bg-hover",
            )}
          >
            <button
              type="button"
              aria-pressed={current}
              title={prompt.text}
              onClick={() => {
                onPick(prompt.text);
                putIn(field, prompt.text);
              }}
              className="h-full min-w-0 truncate pl-2 text-label font-normal text-ink"
            >
              {prompt.text}
            </button>
            <button
              type="button"
              aria-label={`Unpin ${prompt.text}`}
              title="Unpin"
              onClick={() => unpinPrompt(prompt.text, prompt.mode)}
              className="mx-0.5 grid size-5 shrink-0 place-items-center rounded-sm text-ink-muted opacity-0 group-hover/chip:opacity-100 hover:text-ink focus-visible:opacity-100"
            >
              <Icon name="close" />
            </button>
          </li>
        );
      })}
      <li>
        <Button
          size="sm"
          disabled={!written.trim()}
          aria-pressed={writtenPinned}
          onClick={() =>
            writtenPinned
              ? unpinPrompt(written, mode)
              : pinPrompt(written, mode)
          }
          className="text-ink-muted"
        >
          <Icon name={writtenPinned ? "pinned" : "pin"} />
          {writtenPinned ? "Pinned" : "Pin this prompt"}
        </Button>
      </li>
    </ul>
  );
}
