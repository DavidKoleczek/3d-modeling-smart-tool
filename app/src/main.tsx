import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Notice } from "@/components/ui/notice";
import { describe } from "@/lib/errors";
import { connect } from "@/lib/host";
import { loadSettings } from "@/lib/settings";
import { loadWindowsApp } from "@/lib/windowsApp";
import { refreshWorkspaces } from "@/lib/workspaces";

const root = createRoot(document.getElementById("root")!);

try {
  await connect();
  // Before the view first paints, so it opens in the person's theme and layout, on the workspace the app shows, with
  // what the Windows app keeps when it started the server.
  await Promise.all([loadSettings(), refreshWorkspaces(), loadWindowsApp()]);
  root.render(
    <StrictMode>
      <TooltipProvider>
        <ErrorBoundary what="The app" className="m-4">
          <App />
        </ErrorBoundary>
      </TooltipProvider>
    </StrictMode>,
  );
} catch (cause) {
  root.render(
    <Notice title="Could not connect to the host." className="m-4">
      {describe(cause)}
    </Notice>,
  );
}
