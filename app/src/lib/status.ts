import type { ModelStatus } from "@/lib/api";

const LABELS: Record<ModelStatus, string> = {
  running: "Working",
  crashed: "Crashed",
  done: "Done",
  failed: "Failed",
  cancelled: "Stopped",
  "timed-out": "Timed out",
};

/** A status's name, with `null` as a model never built. */
export function statusLabel(status: ModelStatus | null): string {
  return status === null ? "Not built" : LABELS[status];
}

export function failed(status: ModelStatus | null): boolean {
  return status === "failed" || status === "crashed" || status === "timed-out";
}
