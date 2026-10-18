import { Dimension } from "@/components/ui/dimension";
import type { ReasoningEffort } from "@/lib/api";
import { effortLabel, type Intelligence } from "@/lib/intelligence";
import type { Run } from "@/lib/runs";
import { timeOfDay } from "@/lib/time";

/** Where a run starts: its number, when, the AI model and effort it ran on, and whether it continued the session. */
export function RunDivider({
  run,
  intelligence,
}: {
  run: Run;
  intelligence: Intelligence;
}) {
  const data = run.request?.data ?? {};
  const parts = [`Run ${run.number}`, timeOfDay(run.started)];
  if (typeof data.model === "string") {
    parts.push(intelligence.label(data.model));
  }
  if (typeof data.reasoning_effort === "string") {
    parts.push(
      effortLabel(data.reasoning_effort as ReasoningEffort).toLowerCase(),
    );
  }
  if (data.resumed) {
    parts.push("same session");
  } else if (run.number > 1 && run.request) {
    parts.push("fresh session");
  }
  return (
    <li className="shrink-0">
      <Dimension tone="control">{parts.join(" · ")}</Dimension>
    </li>
  );
}
