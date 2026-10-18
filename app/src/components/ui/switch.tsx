import { Switch as SwitchPrimitive } from "@base-ui/react/switch";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** An on or off setting, labeled beside it; the label reads in ink while it is on. */
export function Switch({
  checked,
  onChange,
  children,
  title,
  className,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <label
      title={title}
      className={cn(
        "inline-flex shrink-0 cursor-default items-center gap-1.5 text-label whitespace-nowrap select-none",
        checked ? "text-ink" : "text-ink-muted",
        className,
      )}
    >
      <SwitchPrimitive.Root
        checked={checked}
        onCheckedChange={(next) => onChange(next)}
        className="flex h-4 w-7 shrink-0 rounded-sm border border-line-control bg-field p-0.5 transition-colors data-checked:border-accent data-checked:bg-accent"
      >
        <SwitchPrimitive.Thumb className="size-2.5 rounded-[2px] bg-ink-muted transition-[translate,background-color] data-checked:translate-x-3 data-checked:bg-on-accent" />
      </SwitchPrimitive.Root>
      {children}
    </label>
  );
}
