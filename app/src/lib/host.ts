import {
  App,
  type McpUiDisplayMode,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";

import { setHostTheme } from "@/lib/theme";
import { QuietPostMessageTransport } from "@/lib/transport";

export const app = new App(
  { name: "3D Modeling", version: "1.0.0" },
  { availableDisplayModes: ["inline", "fullscreen"] },
);

type Display = { mode: McpUiDisplayMode; available: McpUiDisplayMode[] };

const displayListeners = new Set<(display: Display) => void>();
let display: Display = { mode: "inline", available: [] };

/** Calls `listener` with how the host shows the view now and which modes it offers, then each time that changes. */
export function onDisplay(listener: (display: Display) => void): () => void {
  listener(display);
  displayListeners.add(listener);
  return () => {
    displayListeners.delete(listener);
  };
}

/** Ask the host to show the view another way, such as fullscreen; it may refuse, and says which it chose. */
export async function requestDisplayMode(mode: McpUiDisplayMode) {
  await app.requestDisplayMode({ mode });
}

// Only the theme and display mode: the view keeps its own fonts and palette, so it looks the same in every host.
function applyHostContext(context: McpUiHostContext) {
  if (context.theme) {
    setHostTheme(context.theme);
  }
  if (context.displayMode || context.availableDisplayModes) {
    display = {
      mode: context.displayMode ?? display.mode,
      available: context.availableDisplayModes ?? display.available,
    };
    for (const listener of displayListeners) {
      listener(display);
    }
  }
}

app.addEventListener("hostcontextchanged", applyHostContext);

export async function connect(): Promise<void> {
  if (window.parent === window) {
    throw new Error(
      "This page is an MCP App view and needs a host. Ask your agent to call `open_app`.",
    );
  }
  await app.connect(
    new QuietPostMessageTransport(window.parent, window.parent),
  );
  const context = app.getHostContext();
  if (context) {
    applyHostContext(context);
  }
}
