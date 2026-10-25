import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";

export type ViewTool = "grid" | "wireframe" | "dimensions" | "rig" | "surface";

const TOOLS: { tool: ViewTool; label: string; key: string; icon: IconName }[] =
  [
    { tool: "grid", label: "Grid", key: "G", icon: "grid" },
    { tool: "wireframe", label: "Wireframe", key: "W", icon: "wireframe" },
    { tool: "dimensions", label: "Dimensions", key: "D", icon: "measure" },
    { tool: "rig", label: "Rig", key: "R", icon: "rig" },
    { tool: "surface", label: "Surface", key: "S", icon: "surface" },
  ];

function Divider() {
  return <span aria-hidden className="mx-0.5 h-4 w-px bg-line" />;
}

/**
 * The viewport's tools: Fit, then the toggles for the grid, mesh edges, dimension lines, the rig, and the surface, which work on
 * the live view and so wait while a marked view is held still. Compact, where there is no room in the top bar, it also
 * switches to the renders and the checks.
 */
export function ViewportToolbar({
  on,
  onToggle,
  onFit,
  locked,
  compact,
  onRenders,
  onChecks,
}: {
  on: Record<ViewTool, boolean>;
  onToggle: (tool: ViewTool) => void;
  onFit: () => void;
  locked: boolean;
  compact: boolean;
  onRenders?: () => void;
  onChecks?: () => void;
}) {
  const size = compact ? "sm" : "md";
  const iconSize = compact ? 16 : 20;
  return (
    <div
      role="toolbar"
      aria-label="Viewport"
      className="flex items-center gap-0.5 rounded-md border border-line bg-panel p-0.75"
    >
      <Tooltip content="Fit the model" keys="F">
        <Button
          size={size}
          icon
          aria-label="Fit the model"
          disabled={locked}
          onClick={onFit}
        >
          <Icon name="fit" size={iconSize} />
        </Button>
      </Tooltip>
      <Divider />
      {TOOLS.map(({ tool, label, key, icon }) => (
        <Tooltip key={tool} content={label} keys={key}>
          <Button
            size={size}
            icon
            aria-label={label}
            aria-pressed={on[tool]}
            disabled={locked}
            onClick={() => onToggle(tool)}
          >
            <Icon name={icon} size={iconSize} />
          </Button>
        </Tooltip>
      ))}
      {(onRenders || onChecks) && <Divider />}
      {onRenders && (
        <Tooltip content="Renders" keys="2">
          <Button size={size} icon aria-label="Renders" onClick={onRenders}>
            <Icon name="image" size={iconSize} />
          </Button>
        </Tooltip>
      )}
      {onChecks && (
        <Tooltip content="Checks" keys="3">
          <Button size={size} icon aria-label="Checks" onClick={onChecks}>
            <Icon name="report" size={iconSize} />
          </Button>
        </Tooltip>
      )}
    </div>
  );
}
