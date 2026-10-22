import { useCallback, useEffect, useRef, useState } from "react";
import { usePanelRef } from "react-resizable-panels";

import { ActivityPanel } from "@/components/ActivityPanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ModelList, type Picker } from "@/components/ModelList";
import {
  NewModelDialog,
  type NewModelRequest,
} from "@/components/NewModelDialog";
import { ShortcutsDialog } from "@/components/ShortcutsDialog";
import { StatusBar } from "@/components/StatusBar";
import { TopBar, type NarrowPane, type Pane } from "@/components/TopBar";
import { Segmented } from "@/components/ui/segmented";
import { Viewport, type ViewMode } from "@/components/Viewport";
import { Workspace } from "@/components/Workspace";
import { onDisplay, requestDisplayMode } from "@/lib/host";
import { useIntelligence } from "@/lib/intelligence";
import { paneLayout, useBreakpoint } from "@/lib/layout";
import { useModels } from "@/lib/models";
import type { Handoff, NextRequest } from "@/lib/requests";
import { useShortcuts } from "@/lib/shortcuts";
import { updateSettings, useSettings } from "@/lib/settings";
import { counted, dimensions, type SceneStats } from "@/lib/stats";
import { cn } from "@/lib/utils";

function App() {
  const [root, breakpoint, width] = useBreakpoint();
  const [display, setDisplay] = useState({
    fullscreen: false,
    expandable: false,
  });
  const [creating, setCreating] = useState(false);
  const [request, setRequest] = useState<NewModelRequest>({ id: 0 });
  const [narrowPane, setNarrowPane] = useState<NarrowPane>("model");
  const [shortcuts, setShortcuts] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("3d");
  const [fits, setFits] = useState(0);
  const [stats, setStats] = useState<SceneStats | null>(null);
  const { listing, model, error, pick } = useModels();
  // By model, whether the person left Continue session on, which the composer's requests follow.
  const [resumes, setResumes] = useState<Record<string, boolean>>({});
  // Marked views on their way into a model's composer, which may not be showing until its pane opens.
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  // Only ever counts up, so a composer that took one handoff never mistakes the next for it.
  const handoffs = useRef(0);
  const next: NextRequest = {
    intelligence: useIntelligence(model),
    resume: (model && resumes[model.name]) ?? true,
    onResume: (resume) => {
      if (model) {
        setResumes((current) => ({ ...current, [model.name]: resume }));
      }
    },
  };
  const { settings, layouts } = useSettings();
  const panes = { models: usePanelRef(), activity: usePanelRef() };
  const search = useRef<HTMLInputElement>(null);
  // A pane opened or closed from the top bar, which the next layout change saves like a drag.
  const toggled = useRef(false);

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
  const compose = (text: string, files: File[]) => {
    if (!model) {
      return;
    }
    handoffs.current += 1;
    setHandoff({ id: handoffs.current, model: model.name, text, files });
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

  const toggleTool = (tool: "grid" | "wireframe" | "dimensions") =>
    updateSettings((current) => ({ ...current, [tool]: !current[tool] }));

  useShortcuts({
    f: () => setFits((count) => count + 1),
    g: () => toggleTool("grid"),
    w: () => toggleTool("wireframe"),
    d: () => toggleTool("dimensions"),
    "1": () => setViewMode("3d"),
    "2": () => setViewMode("renders"),
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
              ]}
            />
          )
        }
      />
      <main className="flex min-h-0 flex-1">
        <ErrorBoundary what="The workspace" className="m-4 flex-1">
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
            <Workspace
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
