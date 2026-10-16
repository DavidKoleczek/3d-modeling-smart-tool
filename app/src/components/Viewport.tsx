import { Box } from "lucide-react";

/** Where the model being built will render. Empty until there is one. */
export function Viewport() {
  return (
    <section className="relative flex min-h-48 flex-1 items-center justify-center overflow-hidden rounded-xl border bg-muted/40">
      <div
        aria-hidden
        className="absolute inset-0 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] bg-size-[32px_32px] opacity-60"
      />
      <div className="relative flex max-w-xs flex-col items-center gap-3 p-4 text-center">
        <div className="flex size-12 items-center justify-center rounded-xl border bg-background shadow-sm">
          <Box className="size-6 text-primary" />
        </div>
        <p className="text-sm font-medium">No model yet</p>
        <p className="text-sm text-muted-foreground">
          Describe what to build, and the model will appear here as the agent
          works on it.
        </p>
      </div>
    </section>
  );
}
