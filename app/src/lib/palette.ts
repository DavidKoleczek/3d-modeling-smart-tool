import { useEffect, useMemo } from "react";
import {
  ClampToEdgeWrapping,
  DataTexture,
  Mesh,
  MeshBasicMaterial,
  NearestFilter,
  RGBAFormat,
  type BufferGeometry,
  type Material,
  type MeshStandardMaterial,
  type Object3D,
  type Texture,
} from "three";

import { shadeWith, type Detail } from "@/lib/detail";

/**
 * A loaded model's palette, as the check reads it: the base color texture most of its triangles are drawn with, a
 * column for each role and a row for each scheme, named by the `palette` in its material's glTF extras, which three.js
 * loads into `userData`.
 */
export type Palette = {
  texture: Texture;
  /** The emission palette beside it, when it has the palette's layout. */
  glowTexture: Texture | null;
  /** The meshes drawn with it. */
  meshes: Mesh[];
  width: number;
  height: number;
  columns: number;
  rows: number;
  /** A name for each column and row: as declared, or by its place where nothing declares them or they don't fit. */
  roles: string[];
  schemes: string[];
  declared: boolean;
  /** RGBA, top row first, as the image stores it. */
  pixels: Uint8ClampedArray;
  glow: Uint8ClampedArray | null;
  /** By role, the triangles whose UVs land in its swatches. */
  triangles: number[];
  /** The row most triangles land in: the scheme the model shows as built. */
  row: number;
};

/** How the view shows the palette: in which scheme, with which role picked out, and the colors the person tried. */
export type Look = {
  scheme: number;
  focus: number | null;
  /** Colors tried in place of a swatch's, as `#rrggbb`, by `swatchKey`. */
  tried: Record<string, string>;
};

// `MOST_SWATCHES` in check/palette.py: an image with more is a texture painted across the model, not a palette.
const MOST_SWATCHES = 1 << 12;
// How far a picked out role's neighbors fade toward the gray beside them.
const FADED = 0.8;
const GRAY = 128;

/** The key a tried color is under in a `Look`. */
export function swatchKey(column: number, row: number): string {
  return `${column}:${row}`;
}

function hex(pixels: Uint8ClampedArray, offset: number): string {
  return `#${[0, 1, 2]
    .map((channel) => pixels[offset + channel].toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;
}

function center(palette: Palette, column: number, row: number): number {
  const x = Math.floor(((column + 0.5) * palette.width) / palette.columns);
  const y = Math.floor(((row + 0.5) * palette.height) / palette.rows);
  return (y * palette.width + x) * 4;
}

/** A swatch's color as the palette stores it. */
export function swatchColor(palette: Palette, column: number, row: number) {
  return hex(palette.pixels, center(palette, column, row));
}

/** A swatch's glow, or null where the emission palette is black or there is none. */
export function swatchGlow(
  palette: Palette,
  column: number,
  row: number,
): string | null {
  const { glow } = palette;
  if (!glow) {
    return null;
  }
  const offset = center(palette, column, row);
  const lit = [0, 1, 2].some((channel) => glow[offset + channel] > 0);
  return lit ? hex(glow, offset) : null;
}

/** The names a declaration gives one way across the image, when they fit its pixels evenly. */
function fitted(
  declared: unknown,
  pixels: number,
  place: string,
): { count: number; names: string[]; fits: boolean } {
  const names =
    Array.isArray(declared) &&
    declared.length > 0 &&
    declared.every((name) => typeof name === "string" && name)
      ? (declared as string[])
      : null;
  if (names && pixels % names.length === 0) {
    return { count: names.length, names, fits: true };
  }
  return {
    count: pixels,
    names: Array.from(
      { length: pixels },
      (_, index) => `${place} ${index + 1}`,
    ),
    fits: false,
  };
}

function declarationOf(meshes: Mesh[]): Record<string, unknown> | null {
  for (const mesh of meshes) {
    let declared: unknown = (mesh.material as MeshStandardMaterial).userData
      .palette;
    if (typeof declared === "string") {
      try {
        declared = JSON.parse(declared);
      } catch {
        continue;
      }
    }
    if (typeof declared === "object" && declared !== null) {
      return declared as Record<string, unknown>;
    }
  }
  return null;
}

/** An image's pixels, RGBA and top row first. */
function pixelsOf(image: CanvasImageSource, width: number, height: number) {
  const canvas = new OffscreenCanvas(width, height);
  const context = canvas.getContext("2d")!;
  context.drawImage(image, 0, 0);
  return context.getImageData(0, 0, width, height).data;
}

function triangles(geometry: BufferGeometry): number {
  return (geometry.index?.count ?? geometry.attributes.position.count) / 3;
}

/** The palette of a loaded model; null without one, or with a base color image too detailed to be one. */
export function paletteOf(scene: Object3D): Palette | null {
  const drawn = new Map<
    Texture["source"],
    { texture: Texture; meshes: Mesh[] }
  >();
  scene.traverse((object) => {
    if (!(object instanceof Mesh) || Array.isArray(object.material)) {
      return;
    }
    const map = (object.material as MeshStandardMaterial).map;
    if (!map?.image) {
      return;
    }
    const entry = drawn.get(map.source) ?? { texture: map, meshes: [] };
    entry.meshes.push(object);
    drawn.set(map.source, entry);
  });
  const count = (meshes: Mesh[]) =>
    meshes.reduce((sum, mesh) => sum + triangles(mesh.geometry), 0);
  const [found] = [...drawn.values()].sort(
    (one, other) => count(other.meshes) - count(one.meshes),
  );
  if (!found) {
    return null;
  }
  const { texture, meshes } = found;
  const image = texture.image as CanvasImageSource & {
    width: number;
    height: number;
  };
  const { width, height } = image;
  const declared = declarationOf(meshes);
  const across = fitted(declared?.roles, width, "column");
  const down = fitted(declared?.schemes, height, "row");
  if (!width || !height || across.count * down.count > MOST_SWATCHES) {
    return null;
  }
  const emissive = (meshes[0].material as MeshStandardMaterial).emissiveMap;
  const sized = emissive?.image as { width: number; height: number } | null;
  const glowTexture =
    emissive && sized?.width === width && sized.height === height
      ? emissive
      : null;
  const palette: Palette = {
    texture,
    glowTexture,
    meshes,
    width,
    height,
    columns: across.count,
    rows: down.count,
    roles: across.names,
    schemes: down.names,
    declared: declared !== null,
    pixels: pixelsOf(image, width, height),
    glow: glowTexture
      ? pixelsOf(glowTexture.image as CanvasImageSource, width, height)
      : null,
    triangles: new Array<number>(across.count).fill(0),
    row: 0,
  };
  const rows = new Array<number>(down.count).fill(0);
  for (const mesh of meshes) {
    const uv = mesh.geometry.attributes[uvName(texture)];
    if (!uv) {
      continue;
    }
    const index = mesh.geometry.index;
    const corners = index?.count ?? uv.count;
    for (let start = 0; start + 2 < corners; start += 3) {
      const cells = [0, 1, 2].map((corner) => {
        const vertex = index ? index.getX(start + corner) : start + corner;
        return cellAt(palette, uv.getX(vertex), uv.getY(vertex));
      });
      const [first] = cells;
      if (
        first &&
        cells.every(
          (cell) =>
            cell && cell.column === first.column && cell.row === first.row,
        )
      ) {
        palette.triangles[first.column] += 1;
        rows[first.row] += 1;
      }
    }
  }
  palette.row = rows.indexOf(Math.max(...rows));
  return palette;
}

/** The name of the geometry attribute holding the UVs a texture reads. */
function uvName(texture: Texture): string {
  return texture.channel === 0 ? "uv" : `uv${texture.channel}`;
}

/** The swatch a UV lands in, glTF's way up, from the image's top left; null outside the image. */
export function cellAt(
  palette: Palette,
  u: number,
  v: number,
): { column: number; row: number } | null {
  if (u < 0 || u > 1 || v < 0 || v > 1) {
    return null;
  }
  return {
    column: Math.min(Math.floor(u * palette.columns), palette.columns - 1),
    row: Math.min(Math.floor(v * palette.rows), palette.rows - 1),
  };
}

/** Which of a mesh's UV sets the palette reads, as a three.js intersection names it, which gives only the first two. */
export function intersectionUv(palette: Palette): "uv" | "uv1" {
  return palette.texture.channel === 1 ? "uv1" : "uv";
}

/** The textures the color view paints the palette and its glow into. */
type Paintable = { color: DataTexture; glow: DataTexture | null };

/**
 * While `on`, draw the palette's meshes with copies of the palette painted as `look` says: unlit when `flat`, so each
 * face shows its swatch's color as stored, rather than as the viewer's lighting shades it, and shaded by `detail` where
 * it covers them. Call it before the scene is disposed of, so each mesh has its own material back by then.
 */
export function useColorView(
  palette: Palette | null,
  on: boolean,
  look: Look,
  flat: boolean,
  detail: Detail | null,
): void {
  const textures = useMemo(
    () =>
      palette && {
        color: paintable(palette, palette.texture),
        glow: palette.glowTexture && paintable(palette, palette.glowTexture),
      },
    [palette],
  );
  useEffect(() => () => release(textures), [textures]);
  useEffect(() => {
    if (palette && textures && on) {
      paint(textures, palette, look);
    }
  }, [palette, textures, on, look]);
  useEffect(() => {
    if (palette && textures && on) {
      return drawWith(palette, textures, flat, detail);
    }
  }, [palette, textures, on, flat, detail]);
}

function release(textures: Paintable | null): void {
  textures?.color.dispose();
  textures?.glow?.dispose();
}

function paint(textures: Paintable, palette: Palette, look: Look): void {
  const { color, glow } = painted(palette, look);
  textures.color.image.data = color;
  textures.color.needsUpdate = true;
  if (textures.glow && glow) {
    textures.glow.image.data = glow;
    textures.glow.needsUpdate = true;
  }
}

/** Draw the palette's meshes with the painted textures, and return what puts their own materials back. */
function drawWith(
  palette: Palette,
  textures: Paintable,
  flat: boolean,
  detail: Detail | null,
): () => void {
  const kept = new Map<Mesh, Material>();
  const made: Material[] = [];
  for (const mesh of palette.meshes) {
    const own = mesh.material as MeshStandardMaterial;
    kept.set(mesh, own);
    let shown: Material;
    if (flat) {
      shown = new MeshBasicMaterial({ map: textures.color, toneMapped: false });
    } else {
      const lit = own.clone();
      lit.map = textures.color;
      lit.emissiveMap = textures.glow ?? own.emissiveMap;
      shown = lit;
    }
    if (detail?.meshes.includes(mesh)) {
      shadeWith(shown, detail);
    }
    made.push(shown);
    mesh.material = shown;
  }
  return () => {
    for (const [mesh, own] of kept) {
      mesh.material = own;
    }
    for (const material of made) {
      material.dispose();
    }
  };
}

/** What to tell the agent about the colors tried: each swatch, in its scheme, from its color to the one tried. */
export function triedRequest(palette: Palette, tried: Look["tried"]): string {
  const lines = Object.entries(tried).flatMap(([key, color]) => {
    const [column, row] = key.split(":").map(Number);
    const was = swatchColor(palette, column, row);
    return was === color.toUpperCase()
      ? []
      : [
          `- ${palette.roles[column]} in ${palette.schemes[row]}: from ${was} to ${color.toUpperCase()}`,
        ];
  });
  return ["Change these swatches to the colors I tried:", ...lines].join("\n");
}

/** The colors tried that differ from the palette's, by `swatchKey`. */
export function changedColors(
  palette: Palette,
  tried: Look["tried"],
): Look["tried"] {
  return Object.fromEntries(
    Object.entries(tried).filter(([key, color]) => {
      const [column, row] = key.split(":").map(Number);
      return color.toUpperCase() !== swatchColor(palette, column, row);
    }),
  );
}

/** A texture of the palette's size the view paints into, sampled as `like` is but always per pixel. */
function paintable(palette: Palette, like: Texture): DataTexture {
  const texture = new DataTexture(
    new Uint8Array(palette.width * palette.height * 4),
    palette.width,
    palette.height,
    RGBAFormat,
  );
  texture.colorSpace = like.colorSpace;
  texture.channel = like.channel;
  texture.flipY = false;
  texture.magFilter = NearestFilter;
  texture.minFilter = NearestFilter;
  texture.generateMipmaps = false;
  texture.wrapS = ClampToEdgeWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  texture.offset.copy(like.offset);
  texture.repeat.copy(like.repeat);
  texture.center.copy(like.center);
  texture.rotation = like.rotation;
  return texture;
}

/**
 * The palette and its glow as the look shows them. Each row repeats the scheme's, so whichever row the UVs point at
 * shows that scheme, as an app would by moving them a row. Tried colors take their swatches, and a picked out role's
 * neighbors fade.
 */
export function painted(
  palette: Palette,
  look: Look,
): { color: Uint8Array; glow: Uint8Array | null } {
  const { width, height, columns, rows } = palette;
  const color = new Uint8Array(width * height * 4);
  const glow = palette.glow ? new Uint8Array(width * height * 4) : null;
  const across = width / columns;
  const down = height / rows;
  const tried = new Map(
    Object.entries(look.tried).map(([key, value]) => [
      key,
      [1, 3, 5].map((start) => parseInt(value.slice(start, start + 2), 16)),
    ]),
  );
  for (let y = 0; y < height; y += 1) {
    const from = look.scheme * down + (y % down);
    for (let x = 0; x < width; x += 1) {
      const column = Math.floor(x / across);
      const target = (y * width + x) * 4;
      const source = (from * width + x) * 4;
      const faded = look.focus !== null && column !== look.focus;
      const swapped = tried.get(swatchKey(column, look.scheme));
      for (let channel = 0; channel < 4; channel += 1) {
        let value = palette.pixels[source + channel];
        if (swapped && channel < 3) {
          value = swapped[channel];
        }
        if (faded && channel < 3) {
          value += (GRAY - value) * FADED;
        }
        color[target + channel] = value;
        if (glow && palette.glow) {
          const lit = palette.glow[source + channel];
          glow[target + channel] = faded && channel < 3 ? 0 : lit;
        }
      }
    }
  }
  return { color, glow };
}
