import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ViewTool = "grid" | "wireframe" | "dimensions";

const TOOLS: { tool: ViewTool; label: string; key: string; icon: IconName }[] =
  [
    { tool: "grid", label: "Grid", key: "G", icon: "grid" },
    { tool: "wireframe", label: "Wireframe", key: "W", icon: "wireframe" },
    { tool: "dimensions", label: "Dimensions", key: "D", icon: "measure" },
  ];

function Divider() {
  return <span aria-hidden className="mx-0.5 h-4 w-px bg-line" />;
}

/**
 * The viewport's tools: Fit, then the toggles for the grid, mesh edges, and dimension lines. Compact, where there is
 * no room in the top bar, it also switches to the renders.
 */
export function ViewportToolbar({
  on,
  onToggle,
  onFit,
  compact,
  onRenders,
}: {
  on: Record<ViewTool, boolean>;
  onToggle: (tool: ViewTool) => void;
  onFit: () => void;
  compact: boolean;
  onRenders?: () => void;
}) {
  const size = compact ? "sm" : "md";
  const iconSize = compact ? 16 : 20;
  return (
    <div
      role="toolbar"
      aria-label="Viewport"
      className={cn(
        "absolute top-3 left-3 z-10 flex items-center gap-0.5 rounded-md border border-line bg-panel p-0.75",
      )}
    >
      <Tooltip content="Fit the model" keys="F">
        <Button size={size} icon aria-label="Fit the model" onClick={onFit}>
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
            onClick={() => onToggle(tool)}
          >
            <Icon name={icon} size={iconSize} />
          </Button>
        </Tooltip>
      ))}
      {onRenders && (
        <>
          <Divider />
          <Tooltip content="Renders" keys="2">
            <Button size={size} icon aria-label="Renders" onClick={onRenders}>
              <Icon name="image" size={iconSize} />
            </Button>
          </Tooltip>
        </>
      )}
    </div>
  );
}
