import { useCallback, useEffect, useRef, useState } from "react";
import { usePanelRef } from "react-resizable-panels";

import { ActivityPanel } from "@/components/ActivityPanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ModelList, type Picker } from "@/components/ModelList";
import {
  NewModelDialog,
  type NewModelRequest,
} from "@/components/NewModelDialog";
import { Panes } from "@/components/Panes";
import { SettingsMenu } from "@/components/SettingsMenu";
import { ShortcutsDialog } from "@/components/ShortcutsDialog";
import { StatusBar } from "@/components/StatusBar";
import { TopBar, type NarrowPane, type Pane } from "@/components/TopBar";
import { Segmented } from "@/components/ui/segmented";
import { Viewport, type ViewMode } from "@/components/Viewport";
import type { ViewTool } from "@/components/viewport/ViewportToolbar";
import { AppMark, Wordmark } from "@/components/Wordmark";
import { WorkspacePicker } from "@/components/WorkspacePicker";
import type { ModelMode } from "@/lib/api";
import { onDisplay, requestDisplayMode } from "@/lib/host";
import { useIntelligence } from "@/lib/intelligence";
import { paneLayout, useBreakpoint } from "@/lib/layout";
import { loadSteps } from "@/lib/steps";
import { useModels } from "@/lib/models";
import type { Handoff, NextRequest } from "@/lib/requests";
import { useShortcuts } from "@/lib/shortcuts";
import { updateSettings, useSettings } from "@/lib/settings";
import { counted, dimensions, type SceneStats } from "@/lib/stats";
import { cn } from "@/lib/utils";
import { useWorkspaces, useWorkspaceWait } from "@/lib/workspaces";

type Display = { fullscreen: boolean; expandable: boolean };

/**
 * The workspace the app shows, or picking one first when it shows none. Everything of a workspace mounts afresh for
 * each, so nothing of the last one shows in the next.
 */
function App() {
  const [display, setDisplay] = useState<Display>({
    fullscreen: false,
    expandable: false,
  });
  const { shown } = useWorkspaces();
  useWorkspaceWait(shown === null);

  useEffect(
    () =>
      onDisplay(({ mode, available }) =>
        setDisplay({
          fullscreen: mode === "fullscreen",
          expandable: mode !== "fullscreen" && available.includes("fullscreen"),
        }),
      ),
    [],
  );

  return shown === null ? (
    <FirstStep fullscreen={display.fullscreen} />
  ) : (
    <InWorkspace key={shown} display={display} />
  );
}

/** Picking a workspace, in place of everything else, until the app shows one. */
function FirstStep({ fullscreen }: { fullscreen: boolean }) {
  const [root, breakpoint] = useBreakpoint();
  return (
    <div
      ref={root}
      className={cn(
        "flex flex-col overflow-hidden bg-canvas text-ink",
        fullscreen ? "h-dvh" : "h-[560px]",
      )}
    >
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-panel pr-2 pl-3">
        {breakpoint === "narrow" ? (
          <AppMark />
        ) : (
          <h1 className="flex shrink-0 items-center">
            <Wordmark />
          </h1>
        )}
        <span className="flex-1" />
        <SettingsMenu />
      </header>
      <main className="flex min-h-0 flex-1 justify-center overflow-y-auto px-4 py-8">
        <section
          aria-labelledby="choose-workspace"
          className="w-full max-w-110"
        >
          <h2 id="choose-workspace" className="text-title">
            Choose a workspace
          </h2>
          <p className="mt-1 mb-4 text-ink-muted">
            Your project's top-level folder. The app keeps its models in the
            folder's .modeling-3d.
          </p>
          <WorkspacePicker />
        </section>
      </main>
    </div>
  );
}

/** The models of the workspace the app shows, the one in view, and its activity. */
function InWorkspace({ display }: { display: Display }) {
  const [root, breakpoint, width] = useBreakpoint();
  const [creating, setCreating] = useState(false);
  const [request, setRequest] = useState<NewModelRequest>({ id: 0 });
  const [narrowPane, setNarrowPane] = useState<NarrowPane>("model");
  const [shortcuts, setShortcuts] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("3d");
  const [fits, setFits] = useState(0);
  const [stats, setStats] = useState<SceneStats | null>(null);
  const { listing, model, error, pick, rename, remove } = useModels();
  useEffect(() => void loadSteps(), []);
  // By model id, which a rename keeps, the mode the person picked, and whether they switched Continue session on or
  // off since, which the composer's requests follow. A switch holds only until the next run starts, with the id of the
  // run before it, so a fresh session asked for once is continued by the request after.
  const [modes, setModes] = useState<Record<string, ModelMode>>({});
  const [resumes, setResumes] = useState<
    Record<string, { resume: boolean; after: string | null }>
  >({});
  const switched = model && resumes[model.id];
  // Marked views on their way into a model's composer, which may not be showing until its pane opens.
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  // Only ever counts up, so a composer that took one handoff never mistakes the next for it.
  const handoffs = useRef(0);
  const mode = (model && modes[model.id]) || model?.last_run?.mode || "shape";
  const next: NextRequest = {
    intelligence: useIntelligence(model, mode),
    mode,
    onMode: (picked) => {
      if (!model) {
        return;
      }
      setModes((current) => ({ ...current, [model.id]: picked }));
      // Back to what the mode starts with, until the person switches it themselves.
      setResumes((current) => {
        const kept = { ...current };
        delete kept[model.id];
        return kept;
      });
    },
    // On only in the mode of the session it would continue, so switching mode starts a fresh session by default.
    resume:
      switched && switched.after === (model?.last_run?.id ?? null)
        ? switched.resume
        : mode === (model?.last_session?.mode ?? mode),
    onResume: (resume) => {
      if (model) {
        setResumes((current) => ({
          ...current,
          [model.id]: { resume, after: model.last_run?.id ?? null },
        }));
      }
    },
  };
  const { settings, layouts } = useSettings();
  const panes = { models: usePanelRef(), activity: usePanelRef() };
  const search = useRef<HTMLInputElement>(null);
  // A pane opened or closed from the top bar, which the next layout change saves like a drag.
  const toggled = useRef(false);

  const select = (name: string) => {
    setCreating(false);
    void pick(name);
  };
  const startNew = (from?: string) => {
    setRequest((before) => ({ id: before.id + 1, model: from }));
    setCreating(true);
  };
  const picker: Picker = {
    listing,
    selected: model?.name ?? null,
    onSelect: select,
    onNew: () => startNew(),
  };
  const models = listing?.models ?? [];
  const layoutKey = breakpoint === "wide" ? "wide" : "medium";
  const layout = settings[layoutKey];

  const saveLayout = (
    widths: Record<"models" | "activity", number>,
    user: boolean,
  ) => {
    if (!user && !toggled.current) {
      return;
    }
    toggled.current = false;
    updateSettings((current) => ({
      ...current,
      [layoutKey]: {
        models:
          breakpoint === "wide"
            ? paneLayout(widths.models, current[layoutKey].models)
            : current[layoutKey].models,
        activity: paneLayout(widths.activity, current[layoutKey].activity),
      },
    }));
  };

  const togglePane = (pane: Pane) => {
    const panel = panes[pane].current;
    if (!panel) {
      return;
    }
    toggled.current = true;
    if (panel.isCollapsed()) {
      panel.expand();
    } else {
      panel.collapse();
    }
  };

  // Shows the composer the marks went into: Activity alone where there is room for one pane, else its pane, opened.
  // Colors tried in the viewer come with the mode they are asked for in.
  const compose = (text: string, files: File[], mode?: ModelMode) => {
    if (!model) {
      return;
    }
    if (mode && mode !== next.mode) {
      next.onMode(mode);
    }
    handoffs.current += 1;
    setHandoff({ id: handoffs.current, model: model.id, text, files });
    const activity = panes.activity.current;
    if (breakpoint === "narrow") {
      setNarrowPane("activity");
    } else if (activity?.isCollapsed()) {
      toggled.current = true;
      activity.expand();
    }
  };
  const taken = useCallback(
    (id: number) =>
      setHandoff((current) => (current?.id === id ? null : current)),
    [],
  );

  const toggleTool = (tool: ViewTool) =>
    updateSettings((current) => ({ ...current, [tool]: !current[tool] }));

  useShortcuts({
    f: () => setFits((count) => count + 1),
    g: () => toggleTool("grid"),
    w: () => toggleTool("wireframe"),
    d: () => toggleTool("dimensions"),
    r: () => toggleTool("rig"),
    s: () => toggleTool("surface"),
    "1": () => setViewMode("3d"),
    "2": () => setViewMode("renders"),
    "3": () => setViewMode("checks"),
    "[": () => breakpoint === "wide" && togglePane("models"),
    "]": () => breakpoint !== "narrow" && togglePane("activity"),
    n: () => startNew(),
    "/": () => {
      if (breakpoint !== "wide") {
        return;
      }
      if (!layout.models.open) {
        togglePane("models");
      }
      requestAnimationFrame(() => search.current?.focus());
    },
    "?": () => setShortcuts(true),
  });

  const viewport = (
    <Viewport
      listing={listing}
      model={model}
      mode={viewMode}
      onMode={setViewMode}
      compact={breakpoint !== "wide"}
      fit={fits}
      onFit={() => setFits((count) => count + 1)}
      onStats={setStats}
      onNew={() => startNew()}
      onCompose={compose}
    />
  );
  const side = (
    <ActivityPanel
      model={model}
      models={models}
      next={next}
      handoff={handoff}
      onTaken={taken}
    />
  );

  return (
    <div
      ref={root}
      className={cn(
        "flex flex-col overflow-hidden bg-canvas text-ink",
        display.fullscreen ? "h-dvh" : "h-[560px]",
      )}
    >
      <TopBar
        breakpoint={breakpoint}
        picker={picker}
        model={model}
        panes={{ models: layout.models.open, activity: layout.activity.open }}
        onTogglePane={togglePane}
        narrowPane={narrowPane}
        onNarrowPane={setNarrowPane}
        onExpand={
          display.expandable
            ? () => void requestDisplayMode("fullscreen")
            : undefined
        }
        onShortcuts={() => setShortcuts(true)}
        center={
          model?.built && (
            <Segmented
              label="Show"
              value={viewMode}
              onChange={setViewMode}
              options={[
                { value: "3d", label: "3D", icon: "model" },
                { value: "renders", label: "Renders", icon: "image" },
                { value: "checks", label: "Checks", icon: "report" },
              ]}
            />
          )
        }
      />
      <main className="flex min-h-0 flex-1">
        <ErrorBoundary what="This view" className="m-4 flex-1">
          {breakpoint === "narrow" ? (
            <div className="flex min-w-0 flex-1 flex-col">
              {narrowPane === "model" ? (
                <>
                  <div className="flex min-h-0 flex-1">{viewport}</div>
                  <ActivityPanel
                    model={model}
                    models={models}
                    next={next}
                    liveOnly
                  />
                </>
              ) : (
                side
              )}
            </div>
          ) : (
            <Panes
              key={`${layoutKey}-${layouts}`}
              wide={breakpoint === "wide"}
              layout={layout}
              width={width}
              panes={panes}
              models={
                <ModelList
                  {...picker}
                  error={error}
                  search={search}
                  onWorkFrom={startNew}
                  onRename={rename}
                  onDelete={remove}
                />
              }
              viewport={viewport}
              activity={side}
              onChanged={saveLayout}
            />
          )}
        </ErrorBoundary>
      </main>
      {breakpoint === "wide" && display.fullscreen && (
        <StatusBar
          listing={listing}
          model={model}
          stats={
            stats && (
              <>
                <span>{counted(stats.triangles, "tri", "tris")}</span>
                <span>{counted(stats.meshes, "mesh", "meshes")}</span>
                <span>{counted(stats.materials, "material", "materials")}</span>
                <span>{dimensions(stats.size)}</span>
              </>
            )
          }
        />
      )}
      <NewModelDialog
        open={creating}
        onOpenChange={setCreating}
        request={request}
        models={models}
        directory={listing?.directory ?? null}
        onCreated={select}
      />
      <ShortcutsDialog open={shortcuts} onOpenChange={setShortcuts} />
    </div>
  );
}

export default App;
