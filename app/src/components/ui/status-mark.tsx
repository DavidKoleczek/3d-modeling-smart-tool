import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import type { ModelStatus } from "@/lib/api";
import { failed, statusLabel } from "@/lib/status";
import { useElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";

function Elapsed({ since }: { since: string }) {
  return (
    <span className="mono-annotation text-ink-muted">{useElapsed(since)}</span>
  );
}

/**
 * How a model's last run went. Only failures have a hue; done is ink and a check. While it works, `since` adds the
 * time it has been at it.
 */
export function StatusMark({
  status,
  since,
  className,
}: {
  status: ModelStatus | null;
  since?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 shrink-0 items-center gap-1.5 text-label whitespace-nowrap",
        failed(status) && "text-danger",
        status === "cancelled" && "text-ink-muted",
        status === null && "text-ink-muted",
        className,
      )}
    >
      {status === "running" && <LoadingMark />}
      {status === "done" && <Icon name="check" />}
      {failed(status) && <Icon name="warning" />}
      {status === "cancelled" && <Icon name="stop" />}
      {status === null && <Icon name="model" className="text-ink-faint" />}
      {statusLabel(status)}
      {status === "running" && since && <Elapsed since={since} />}
    </span>
  );
}
