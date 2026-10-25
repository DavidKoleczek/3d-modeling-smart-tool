import { useState } from "react";

import { Icon } from "@/components/ui/icon";
import { Markdown } from "@/components/ui/markdown";
import type { ActivityEntry } from "@/lib/api";
import { timeOfDay } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * The check the run made of model.glb as its agent was finishing, and sent it to act on: closed to one line, open to
 * the report as the agent read it, or why the check could not run.
 */
export function CheckedEntry({ entry }: { entry: ActivityEntry }) {
  const [open, setOpen] = useState(false);
  const failed = typeof entry.data.error === "string";
  return (
    <li className="shrink-0 overflow-hidden rounded-md border border-line bg-panel">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex h-7 w-full items-center gap-1.5 px-2 text-left text-label -outline-offset-2 hover:bg-hover"
      >
        <Icon
          name="chevron"
          className={cn(
            "text-ink-muted transition-transform",
            !open && "-rotate-90",
          )}
        />
        <span className={cn("truncate", failed && "text-danger")}>
          {failed
            ? "The check of model.glb couldn't run"
            : "Checked model.glb and sent the agent the report"}
        </span>
        <span className="mono-annotation text-ink-muted">
          {timeOfDay(entry.time, true)}
        </span>
        <span className="flex-1" />
        <Icon
          name={failed ? "warning" : "report"}
          className={failed ? "text-danger" : "text-ink-muted"}
        />
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2">
          <Markdown>{entry.text}</Markdown>
        </div>
      )}
    </li>
  );
}
