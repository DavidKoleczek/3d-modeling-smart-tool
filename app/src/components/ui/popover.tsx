import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import type { ReactNode, RefObject } from "react";

import { POPUP } from "@/components/ui/popup";
import { cn } from "@/lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverClose = PopoverPrimitive.Close;

/** The open popover, placed against its trigger. */
export function PopoverContent({
  side = "bottom",
  align = "end",
  label,
  finalFocus,
  className,
  children,
}: {
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  label?: string;
  /** Where focus goes once it closes, when not back to its trigger. */
  finalFocus?: RefObject<HTMLElement | null>;
  className?: string;
  children: ReactNode;
}) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        side={side}
        align={align}
        sideOffset={4}
        collisionPadding={8}
        className="z-50 outline-none"
      >
        <PopoverPrimitive.Popup
          aria-label={label}
          finalFocus={finalFocus}
          className={cn(POPUP, className)}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}
