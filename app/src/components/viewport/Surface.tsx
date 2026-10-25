import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { Detail, Layers } from "@/lib/detail";
import {
  changedColors,
  swatchColor,
  swatchGlow,
  swatchKey,
  triedRequest,
  type Look,
  type Palette,
} from "@/lib/palette";
import { counted } from "@/lib/stats";
import { cn } from "@/lib/utils";

/**
 * Beside the 3D view, what each face shows: its colors, its detail, or both, as a renderer draws them together. For a
 * palette, each role's swatch in the scheme showing, with its name, color, and triangles, and what glows. Hovering a
 * role fades the rest, and the role under the pointer on the model is marked. A swatch takes a color to try, which the
 * model shows at once, and Send puts the colors tried in the composer to ask for. Flat draws the colors unlit.
 */
export function SurfacePanel({
  palette,
  detail,
  layers,
  onLayers,
  look,
  onLook,
  flat,
  onFlat,
  pointed,
  onSend,
}: {
  palette: Palette | null;
  detail: Detail | null;
  layers: Layers;
  onLayers: (layers: Layers) => void;
  look: Look;
  onLook: (look: Look) => void;
  flat: boolean;
  onFlat: (flat: boolean) => void;
  /** The role under the pointer on the model. */
  pointed: number | null;
  onSend: (text: string) => void;
}) {
  const changed = palette ? changedColors(palette, look.tried) : {};
  const count = Object.keys(changed).length;
  return (
    <aside
      aria-label="Surface"
      className="flex min-h-0 flex-col overflow-hidden rounded-md border border-line bg-panel"
    >
      <header className="shrink-0 border-b border-line px-2.5 py-1.5">
        <div className="flex h-6 items-center gap-1.5 text-label">
          <Icon name="surface" />
          Surface
          <span className="flex-1" />
          {palette && (
            <Switch
              checked={flat}
              onChange={onFlat}
              title="Draw the colors unlit, as the palette stores them"
            >
              Flat
            </Switch>
          )}
        </div>
        {palette && (
          <p className="mono-annotation text-ink-muted">
            {counted(palette.columns, "role", "roles")} ·{" "}
            {counted(palette.rows, "scheme", "schemes")}
          </p>
        )}
        {detail && (
          <p
            className="mono-annotation text-ink-muted"
            title={`${detail.file}, which multiplies the colors by twice its value`}
          >
            Detail {detail.width}x{detail.height}
            {detail.density !== null &&
              ` · ${Math.round(detail.density)} texels/m`}
          </p>
        )}
        {detail && (
          <Segmented
            label="Show"
            size="sm"
            full
            value={layers}
            onChange={onLayers}
            options={[
              { value: "both", label: "Both" },
              { value: "colors", label: "Colors" },
              { value: "detail", label: "Detail" },
            ]}
            className="mt-1"
          />
        )}
        {palette && palette.rows > 1 && (
          <Select
            label="Scheme shown"
            value={String(look.scheme)}
            onChange={(picked) => onLook({ ...look, scheme: Number(picked) })}
            items={palette.schemes.map((scheme, row) => ({
              value: String(row),
              label: row === palette.row ? `${scheme}, as built` : scheme,
            }))}
            className="mt-1 w-full"
          />
        )}
      </header>
      {palette && (
        <ol
          className="min-h-0 overflow-y-auto"
          onPointerLeave={() => onLook({ ...look, focus: null })}
        >
          {palette.roles.map((role, column) => {
            const key = swatchKey(column, look.scheme);
            const color =
              look.tried[key] ?? swatchColor(palette, column, look.scheme);
            const glow = swatchGlow(palette, column, look.scheme);
            return (
              <li
                key={role}
                onPointerEnter={() => onLook({ ...look, focus: column })}
                className={cn(
                  "flex min-w-0 items-center gap-2 border-t border-line px-2.5 py-1.5 first:border-t-0",
                  (pointed === column || look.focus === column) && "bg-hover",
                )}
              >
                <input
                  type="color"
                  value={color.toLowerCase()}
                  onChange={(event) =>
                    onLook({
                      ...look,
                      tried: { ...look.tried, [key]: event.target.value },
                    })
                  }
                  aria-label={`Try a color for ${role} in ${palette.schemes[look.scheme]}`}
                  title="Try another color"
                  className="size-6 shrink-0 cursor-pointer rounded-sm border border-line-control bg-transparent p-0"
                />
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate mono-value",
                    palette.triangles[column] === 0 && "text-ink-muted",
                  )}
                >
                  {role}
                </span>
                {glow && (
                  <span
                    className="mono-annotation text-accent-ink"
                    title={`Glows ${glow}`}
                  >
                    glows
                  </span>
                )}
                <span className="shrink-0 mono-annotation text-ink-muted">
                  {color.toUpperCase()}
                </span>
                <span
                  className="w-10 shrink-0 text-right mono-annotation text-ink-muted"
                  title="Triangles"
                >
                  {palette.triangles[column]}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {palette && !palette.declared && (
        <p className="border-t border-line px-2.5 py-2 text-caption text-ink-muted">
          Its material doesn't declare its roles and schemes, so each is named
          by its place. Color the model to name them.
        </p>
      )}
      {palette && count > 0 && (
        <footer className="flex shrink-0 items-center gap-1 border-t border-line px-2.5 py-1.5">
          <span className="flex-1 mono-annotation text-ink-muted">
            {counted(count, "color tried", "colors tried")}
          </span>
          <Button size="sm" onClick={() => onLook({ ...look, tried: {} })}>
            Reset
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onSend(triedRequest(palette, changed))}
            title="Put the colors tried in the message to the agent, in Color mode"
          >
            <Icon name="send" />
            Send
          </Button>
        </footer>
      )}
    </aside>
  );
}
