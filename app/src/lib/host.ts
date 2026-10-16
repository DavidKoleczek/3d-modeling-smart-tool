import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
  type McpUiDisplayMode,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";

export const app = new App({ name: "Modeling 3D", version: "1.0.0" });

const displayModeListeners = new Set<(mode: McpUiDisplayMode) => void>();
let displayMode: McpUiDisplayMode = "inline";

/** Calls `listener` with how the host shows the view now, then each time that changes. */
export function onDisplayMode(
  listener: (mode: McpUiDisplayMode) => void,
): () => void {
  listener(displayMode);
  displayModeListeners.add(listener);
  return () => {
    displayModeListeners.delete(listener);
  };
}

function applyHostContext(context: McpUiHostContext) {
  if (context.theme) {
    applyDocumentTheme(context.theme);
  }
  if (context.styles?.variables) {
    applyHostStyleVariables(context.styles.variables);
  }
  if (context.styles?.css?.fonts) {
    applyHostFonts(context.styles.css.fonts);
  }
  if (context.displayMode) {
    displayMode = context.displayMode;
    for (const listener of displayModeListeners) {
      listener(displayMode);
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
  await app.connect();
  const context = app.getHostContext();
  if (context) {
    applyHostContext(context);
  }
}
