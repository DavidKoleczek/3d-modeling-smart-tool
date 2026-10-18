import type { ReactNode } from "react";

import type { Picker } from "@/components/ModelList";
import { ModelSwitcher } from "@/components/ModelSwitcher";
import { SettingsMenu } from "@/components/SettingsMenu";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { StatusMark } from "@/components/ui/status-mark";
import { Tooltip } from "@/components/ui/tooltip";
import { AppMark, Wordmark } from "@/components/Wordmark";
import type { ModelSummary } from "@/lib/api";
import type { Breakpoint } from "@/lib/layout";

export type Pane = "models" | "activity";
export type NarrowPane = "model" | "activity";

function Divider() {
  return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line" />;
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

/** The bar along the top: the brand, the model in view and how it is doing, and the app's controls. */
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
