import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { ProgressBar } from "@/components/ui/progress-bar";
import type { Call } from "@/lib/runs";
import { useElapsed } from "@/lib/time";

/**
 * Always in view while a run works, above the composer: how long it has been at it, the step it is on, and Stop.
 */
export function LiveStrip({
  since,
  current,
  onStop,
}: {
  since: string;
  current: { call: Call; number: number } | null;
  onStop: () => void;
}) {
  const elapsed = useElapsed(since);
  return (
    <div className="relative flex shrink-0 items-center gap-2.5 border-t border-line bg-accent-soft py-1.75 pr-2 pl-3">
      <ProgressBar className="-top-px" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-2 text-label">
          <LoadingMark size={12} />
          Working
          <span className="mono-annotation text-ink">{elapsed}</span>
        </span>
        {current && (
          <span
            title={current.call.target}
            className="truncate mono-annotation text-ink-muted"
          >
            Step {current.number}, {current.call.doing.toLowerCase()}{" "}
            {current.call.target}
          </span>
        )}
      </div>
      <Button variant="secondary" size="sm" onClick={onStop}>
        <Icon name="stop" />
        Stop
      </Button>
    </div>
  );
}
