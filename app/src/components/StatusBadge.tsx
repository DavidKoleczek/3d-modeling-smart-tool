import { LoaderCircle } from "lucide-react";

import type { ModelStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const LABELS: Record<ModelStatus, string> = {
  running: "Working",
  crashed: "Crashed",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  "timed-out": "Timed out",
};

/** How a model's last run went, with `running` as the agent still at work. */
export function StatusBadge({ status }: { status: ModelStatus | null }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium",
        status === "running" && "bg-primary/10 text-primary",
        (status === "crashed" ||
          status === "failed" ||
          status === "timed-out") &&
          "bg-destructive/10 text-destructive",
        (status === null || status === "done" || status === "cancelled") &&
          "bg-muted text-muted-foreground",
      )}
    >
      {status === "running" && <LoaderCircle className="size-3 animate-spin" />}
      {status === null ? "Not built" : LABELS[status]}
    </span>
  );
}
