import { useCallback, useState } from "react";

import type { PaneLayout } from "@/lib/api";

/** How much room the view has, from its own width rather than the host's display mode. */
export type Breakpoint = "wide" | "medium" | "narrow";

const WIDE = 1100;
const MEDIUM = 640;

export function breakpointOf(width: number): Breakpoint {
  if (width >= WIDE) {
    return "wide";
  }
  return width >= MEDIUM ? "medium" : "narrow";
}

/** A ref for the view's root, and its width and the breakpoint that falls in, kept up to date as it is resized. */
export function useBreakpoint(): [
  (element: HTMLElement | null) => void,
  Breakpoint,
  number,
] {
  const [width, setWidth] = useState(() => window.innerWidth);
  const ref = useCallback((element: HTMLElement | null) => {
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, breakpointOf(width), width];
}

/** A pane as the settings keep it, from its width now; a closed pane keeps the width it comes back at. */
export function paneLayout(width: number, before: PaneLayout): PaneLayout {
  return width > 0 ? { open: true, size: width } : { ...before, open: false };
}
