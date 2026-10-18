import { useRef, useState, type ReactNode, type RefObject } from "react";
import {
  Group,
  Panel,
  type Layout,
  type PanelImperativeHandle,
} from "react-resizable-panels";

import { ResizeHandle } from "@/components/ui/resizable";
import type { AppLayout, PaneLayout } from "@/lib/api";

const MODELS = { min: 200, max: 360, default: 248 };
const VIEWPORT_MIN = 360;
const ACTIVITY_WIDE = { min: 320, max: "45%", default: 400 };
const ACTIVITY_MEDIUM = { min: 300, default: 0.42 };

export type PaneRefs = {
  models: RefObject<PanelImperativeHandle | null>;
  activity: RefObject<PanelImperativeHandle | null>;
};

/** Where the panes start: as the person left them, as percentages of the width the workspace has now. */
function startingLayout(
  wide: boolean,
  layout: AppLayout,
  width: number,
): Layout | undefined {
  if (width <= 0) {
    return undefined;
  }
  const pixels = (pane: PaneLayout, fallback: number) =>
    pane.open ? (pane.size ?? fallback) : 0;
  const share = (size: number) => (size / width) * 100;
  const activity = share(
    pixels(
      layout.activity,
      wide ? ACTIVITY_WIDE.default : ACTIVITY_MEDIUM.default * width,
    ),
  );
  const models = wide ? share(pixels(layout.models, MODELS.default)) : 0;
  return wide
    ? { models, viewport: 100 - models - activity, activity }
    : { viewport: 100 - activity, activity };
}

/**
 * The viewport between Your models and Activity, each resizable and collapsible; at medium widths, the viewport and
 * Activity alone. The viewport never goes below 360px.
 */
export function Workspace({
  wide,
  layout,
  width,
  panes,
  models,
  viewport,
  activity,
  onChanged,
}: {
  wide: boolean;
  layout: AppLayout;
  width: number;
  panes: PaneRefs;
  models: ReactNode;
  viewport: ReactNode;
  activity: ReactNode;
  /** Each side pane's width in pixels after a change, 0 when closed, and whether the person made the change. */
  onChanged: (
    widths: Record<"models" | "activity", number>,
    user: boolean,
  ) => void;
}) {
  // Read once: the group takes its layout from here only as it mounts.
  const [start] = useState(() => startingLayout(wide, layout, width));
  const group = useRef<HTMLDivElement>(null);
  return (
    <Group
      orientation="horizontal"
      defaultLayout={start}
      elementRef={group}
      onLayoutChanged={(changed, meta) => {
        const room = group.current?.offsetWidth ?? 0;
        const pixels = (id: string) =>
          Math.round(((changed[id] ?? 0) / 100) * room);
        onChanged(
          { models: pixels("models"), activity: pixels("activity") },
          meta.isUserInteraction,
        );
      }}
      className="min-h-0 flex-1"
    >
      {wide && (
        <>
          <Panel
            id="models"
            panelRef={panes.models}
            collapsible
            collapsedSize={0}
            minSize={MODELS.min}
            maxSize={MODELS.max}
            defaultSize={MODELS.default}
            groupResizeBehavior="preserve-pixel-size"
            className="h-full"
          >
            {models}
          </Panel>
          <ResizeHandle label="Resize Your models" />
        </>
      )}
      <Panel id="viewport" minSize={VIEWPORT_MIN} className="h-full">
        {viewport}
      </Panel>
      <ResizeHandle label="Resize Activity" />
      <Panel
        id="activity"
        panelRef={panes.activity}
        collapsible
        collapsedSize={0}
        minSize={wide ? ACTIVITY_WIDE.min : ACTIVITY_MEDIUM.min}
        maxSize={wide ? ACTIVITY_WIDE.max : undefined}
        defaultSize={
          wide ? ACTIVITY_WIDE.default : `${ACTIVITY_MEDIUM.default * 100}%`
        }
        groupResizeBehavior={wide ? "preserve-pixel-size" : undefined}
        className="h-full"
      >
        {activity}
      </Panel>
    </Group>
  );
}
