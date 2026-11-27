import { useState, type ReactNode } from "react";

import type { Picker } from "@/components/ModelList";
import { ModelSwitcher } from "@/components/ModelSwitcher";
import { SettingsMenu } from "@/components/SettingsMenu";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { StatusMark } from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import { AppMark, Wordmark } from "@/components/Wordmark";
import { WorkspacePicker } from "@/components/WorkspacePicker";
import type { ModelSummary } from "@/lib/api";
import type { Breakpoint } from "@/lib/layout";
import { baseName } from "@/lib/library";
import { refreshWorkspaces, useWorkspaces } from "@/lib/workspaces";

export type Pane = "models" | "activity";
export type NarrowPane = "model" | "activity";

function Divider() {
  return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line" />;
}

/** The workspace the app shows, by its folder's name, opening the workspaces to switch to; its icon alone when narrow. */
function WorkspaceSwitcher({ compact }: { compact: boolean }) {
  const { shown } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const name = shown === null ? "Workspace" : baseName(shown);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        // Another app may have opened, or a folder gone, since they were read.
        if (next) {
          void refreshWorkspaces();
        }
      }}
    >
      <Tooltip content={shown ?? "Workspace"}>
        <PopoverTrigger
          render={
            <Button
              size="sm"
              icon={compact}
              aria-label={`Workspace: ${name}`}
              className={compact ? undefined : "min-w-0 shrink"}
            />
          }
        >
          <Icon name="folder" />
          {!compact && (
            <>
              <span className="min-w-0 truncate text-body font-medium">
                {name}
              </span>
              <Icon name="chevron" className="text-ink-muted" />
            </>
          )}
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent
        label="Workspaces"
        align="start"
        className="w-90 max-w-[calc(100vw-16px)]"
      >
        <p className="px-2 pt-1 pb-1.5 text-label text-ink-muted">Workspaces</p>
        <WorkspacePicker onPicked={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}

function PaneToggle({
  pane,
  open,
  onToggle,
}: {
  pane: Pane;
  open: boolean;
  onToggle: (pane: Pane) => void;
}) {
  const label = pane === "models" ? "Your models" : "Activity";
  return (
    <Tooltip content={label} keys={pane === "models" ? "[" : "]"}>
      <Button
        size="sm"
        icon
        aria-label={label}
        aria-pressed={open}
        onClick={() => onToggle(pane)}
      >
        <Icon name={pane === "models" ? "sidebar-left" : "sidebar-right"} />
      </Button>
    </Tooltip>
  );
}

/** The bar along the top: the brand, the workspace, the model in view and how it is doing, and the app's controls. */
export function TopBar({
  breakpoint,
  picker,
  model,
  center,
  panes,
  onTogglePane,
  narrowPane,
  onNarrowPane,
  onExpand,
  onShortcuts,
}: {
  breakpoint: Breakpoint;
  picker: Picker;
  model: ModelSummary | null;
  center?: ReactNode;
  panes: Record<Pane, boolean>;
  onTogglePane: (pane: Pane) => void;
  narrowPane: NarrowPane;
  onNarrowPane: (pane: NarrowPane) => void;
  /** Asks the host for fullscreen; absent when the view is fullscreen already, or the host has no such mode. */
  onExpand?: () => void;
  onShortcuts: () => void;
}) {
  const state = model && model.status !== "done" && (
    <StatusMark status={model.status} since={model.last_run?.started} />
  );
  return (
    <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-panel pr-2 pl-3">
      {breakpoint === "narrow" ? (
        <AppMark />
      ) : (
        <h1 className="flex shrink-0 items-center">
          <Wordmark />
        </h1>
      )}
      {breakpoint !== "narrow" && <Divider />}
      <WorkspaceSwitcher compact={breakpoint === "narrow"} />
      {(breakpoint !== "wide" || model) && (
        <span aria-hidden className="shrink-0 text-ink-faint">
          /
        </span>
      )}
      {breakpoint === "wide" ? (
        model && (
          <span className="min-w-0 truncate font-medium">{model.name}</span>
        )
      ) : (
        <ModelSwitcher {...picker} />
      )}
      {breakpoint !== "narrow" && state}
      <span className="flex-1" />
      {breakpoint === "wide" && center}
      {breakpoint === "wide" && <span className="flex-1" />}
      {breakpoint === "narrow" && (
        <Segmented
          label="Show"
          size="sm"
          value={narrowPane}
          onChange={onNarrowPane}
          options={[
            { value: "model", label: "Model" },
            { value: "activity", label: "Activity" },
          ]}
        />
      )}
      {breakpoint === "wide" ? (
        <Button variant="secondary" size="sm" onClick={picker.onNew}>
          <Icon name="add" />
          New model
        </Button>
      ) : (
        breakpoint === "medium" && (
          <Tooltip content="New model" keys="N">
            <Button
              size="sm"
              icon
              aria-label="New model"
              onClick={picker.onNew}
            >
              <Icon name="add" />
            </Button>
          </Tooltip>
        )
      )}
      {breakpoint === "wide" && <Divider />}
      {breakpoint === "wide" && (
        <PaneToggle pane="models" open={panes.models} onToggle={onTogglePane} />
      )}
      {breakpoint !== "narrow" && (
        <PaneToggle
          pane="activity"
          open={panes.activity}
          onToggle={onTogglePane}
        />
      )}
      <SettingsMenu onShortcuts={onShortcuts} />
      {onExpand && (
        <Tooltip content="Expand">
          <Button size="sm" icon aria-label="Expand" onClick={onExpand}>
            <Icon name="expand" />
          </Button>
        </Tooltip>
      )}
    </header>
  );
}
