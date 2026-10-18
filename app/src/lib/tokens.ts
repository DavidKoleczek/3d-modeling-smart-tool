import { Color } from "three";

import { useTheme, type Theme } from "@/lib/theme";

/** The token colors the 3D scene draws with, for a theme. */
export type SceneColors = {
  canvas: string;
  gridCell: string;
  gridSection: string;
  accentInk: string;
  ink: string;
  shadow: string;
};

const cache = new Map<Theme, SceneColors>();

function token(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
}

/** `line-control` at `amount` over the canvas, since the grid's lines take no alpha of their own. */
function over(canvas: string, amount: number): string {
  return `#${new Color(canvas).lerp(new Color(token("line-control")), amount).getHexString()}`;
}

function read(theme: Theme): SceneColors {
  const canvas = token("canvas");
  return {
    canvas,
    gridCell: over(canvas, 0.2),
    gridSection: over(canvas, 0.5),
    accentInk: token("accent-ink"),
    ink: token("ink"),
    shadow: theme === "dark" ? "#000000" : "#12161c",
  };
}

/** The scene's colors from the tokens, following a change of theme. */
export function useSceneColors(): SceneColors {
  const theme = useTheme();
  if (!cache.has(theme)) {
    cache.set(theme, read(theme));
  }
  return cache.get(theme)!;
}
