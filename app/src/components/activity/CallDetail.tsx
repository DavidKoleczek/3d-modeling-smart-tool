import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { Markdown } from "@/components/ui/markdown";

import type { ToolCall } from "@/lib/api";
import { useToolCall } from "@/lib/calls";
import type { Call } from "@/lib/runs";
import { cn } from "@/lib/utils";

type Section = { label: string; text: string; failed?: boolean };

// The arguments that say the most about each tool, under the label each shows with. A Read's file is already on its
// row. Any other tool shows all it was called with.
const SHOWN: Record<string, [string, string][]> = {
  Bash: [["command", "Command"]],
  Edit: [
    ["old_string", "Replaced"],
    ["new_string", "With"],
  ],
  Write: [["content", "Wrote"]],
  Read: [],
};

function sectionsOf(call: ToolCall): Section[] {
  const shown = SHOWN[call.name];
  const sections: Section[] = shown
    ? shown.flatMap(([argument, label]) => {
        const value = call.input[argument];
        return typeof value === "string" && value
          ? [{ label, text: value }]
          : [];
      })
    : Object.keys(call.input).length > 0
      ? [{ label: "Called with", text: JSON.stringify(call.input, null, 2) }]
      : [];
  if (call.output) {
    sections.push({
      label: call.failed ? "Error" : "Output",
      text: call.output,
      failed: call.failed,
    });
  }
  return sections;
}

function lines(sections: Section[]): number {
  return sections.reduce(
    (total, section) => total + section.text.split("\n").length,
    0,
  );
}

/**
 * Detail under a step's row, a few lines of it at first, and all of it, scrolling, once asked for. `lines` counts what
 * there is to show, for the person to judge before they ask.
 */
function Expandable({
  lines,
  children,
}: {
  lines?: number;
  children: ReactNode;
}) {
  const [all, setAll] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) {
      return;
    }
    const measure = () =>
      setOverflows(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [all]);

  return (
    <>
      <div className="relative">
        <div
          ref={box}
          className={cn(
            "flex flex-col gap-2 rounded-md border border-line bg-field px-2.5 py-2",
            all
              ? "max-h-[min(60vh,32rem)] overflow-auto"
              : "max-h-40 overflow-hidden",
          )}
        >
          {children}
        </div>
        {!all && overflows && (
          <div className="pointer-events-none absolute inset-x-px bottom-px h-10 rounded-b-md bg-linear-to-t from-field" />
        )}
      </div>
      {(all || overflows) && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="mt-1 mono-annotation text-accent-ink hover:underline"
        >
          {all
            ? "Show less"
            : lines === undefined
              ? "Show all"
              : `Show all ${lines} lines`}
        </button>
      )}
    </>
  );
}

/** A tool call in full under its row: what it was called with and what came back. */
export function CallDetail({ model, call }: { model: string; call: Call }) {
  const { call: full, error } = useToolCall(
    model,
    call.step.entry.run_id,
    String(call.step.entry.data.id),
    call.finished ?? "running",
  );
  const sections = full ? sectionsOf(full) : [];

  let note: string | null = null;
  if (full === null) {
    note = error ?? "Reading...";
  } else if (full.output === null) {
    note = "Still running.";
  } else if (sections.length === 0) {
    note = "Nothing came back as text.";
  }

  return (
    <div className="px-2 pb-2 pl-8">
      {sections.length > 0 && (
        <Expandable lines={lines(sections)}>
          {sections.map((section) => (
            <section key={section.label}>
              <h4 className="mb-0.5 mono-annotation text-ink-muted">
                {section.label}
              </h4>
              <pre
                className={cn(
                  "mono-value font-normal wrap-break-word whitespace-pre-wrap",
                  section.failed && "text-danger",
                )}
              >
                {section.text}
              </pre>
            </section>
          ))}
        </Expandable>
      )}
      {note && (
        <p
          className={cn(
            "mono-annotation",
            error ? "text-danger" : "text-ink-muted",
            sections.length > 0 && "mt-1.5",
          )}
        >
          {note}
        </p>
      )}
    </div>
  );
}

/** What the agent reasoned under its row, in the summary it gave of it. */
export function ReasoningDetail({ summary }: { summary: string }) {
  return (
    <div className="px-2 pb-2 pl-8">
      <Expandable>
        <Markdown className="text-label">{summary}</Markdown>
      </Expandable>
    </div>
  );
}
