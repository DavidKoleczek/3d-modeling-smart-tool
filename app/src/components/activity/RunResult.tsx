import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import type { ModelStatus } from "@/lib/api";
import { between } from "@/lib/time";

/** What a run left, such as "model.glb · model.py · 5 renders". */
function leftBehind(files: string[]): string {
  const renders = files.filter((file) => file.startsWith("renders/")).length;
  return [
    ...["model.glb", "model.py"].filter((file) => files.includes(file)),
    ...(renders > 0
      ? [`${renders} ${renders === 1 ? "render" : "renders"}`]
      : []),
  ].join(" · ");
}

/** How a run ended, then what to do about it; its last words are already in what the agent said. */
export function RunResult({
  status,
  started,
  ended,
  error,
  files,
}: {
  status: ModelStatus;
  started: string;
  /** None for a run whose process stopped without saying how. */
  ended: string | null;
  error: string | null;
  files: string[];
}) {
  const took = ended ? between(started, ended) : null;
  if (status === "done") {
    const left = leftBehind(files);
    return (
      <li className="flex shrink-0 flex-wrap items-center gap-1.5">
        <Icon name="check" />
        <span className="text-label">Done in {took}</span>
        {left && <span className="mono-annotation text-ink-muted">{left}</span>}
      </li>
    );
  }
  if (status === "cancelled") {
    return (
      <li className="shrink-0">
        <Notice tone="neutral" title={`Stopped after ${took}.`}>
          Ask for the change again to continue the same session.
        </Notice>
      </li>
    );
  }
  const titles: Partial<Record<ModelStatus, string>> = {
    failed: `Failed after ${took}.`,
    "timed-out": `Timed out after ${took}.`,
    crashed: "The run stopped unexpectedly.",
  };
  const next =
    status === "crashed"
      ? "Its process ended without saying why. Ask again to continue the same session."
      : "Ask again, or switch Continue session off to start fresh.";
  return (
    <li className="shrink-0">
      <Notice title={titles[status] ?? "The run ended."}>
        {error ? `${error} ${next}` : next}
      </Notice>
    </li>
  );
}
