import { useEffect } from "react";
import {
  ClampToEdgeWrapping,
  LinearFilter,
  LinearMipmapLinearFilter,
  Mesh,
  Texture,
  Vector3,
  type Material,
  type Object3D,
} from "three";

import { readModelFile } from "@/lib/api";

/**
 * A loaded model's detail texture: the grayscale image beside its model.glb that its materials name as `detail` in
 * their glTF extras, which three.js loads into `userData`. A renderer multiplies the base color by twice it, read on the
 * second set of texture coordinates, since glTF has no place for it.
 */
export type Detail = {
  file: string;
  texture: Texture;
  /** The meshes drawn with a material that declares it. */
  meshes: Mesh[];
  width: number;
  height: number;
  /** Texels a meter along the edges of the faces it covers, in the middle; null where none is long enough. */
  density: number | null;
  /** What every material shaded by it reads, shared so the view changes what shows without recompiling them. */
  uniforms: DetailUniforms;
};

/** What the view shows of each face: its colors shaded by the detail, its colors alone, or the detail alone. */
export type Layers = "both" | "colors" | "detail";

type DetailUniforms = {
  detailMap: { value: Texture };
  detailOn: { value: number };
  detailAlone: { value: number };
};

// Mid gray as stored, in the linear light the shader works in, which the detail is shown alone on.
const MID_GRAY = 0.214;
// `MEASURED_TEXELS` in check/detail.py: how long an edge must be on the texture to measure its texels a meter.
const MEASURED_TEXELS = 1;
const ANISOTROPY = 8;
// One program for every material shaded by a detail, since what it shades by are uniforms.
const PROGRAM = "modeling-3d-detail";

const VERTEX = `
#ifndef USE_UV1
attribute vec2 uv1;
#endif
varying vec2 vDetailUv;
`;
const FRAGMENT = `
uniform sampler2D detailMap;
uniform float detailOn;
uniform float detailAlone;
varying vec2 vDetailUv;
`;
const SHADING = `
diffuseColor.rgb = mix( diffuseColor.rgb, vec3( ${MID_GRAY} ), detailAlone )
  * mix( 1.0, 2.0 * texture2D( detailMap, vDetailUv ).r, detailOn );
`;

/** The file a loaded model's materials name as their detail, and the meshes drawn with them; null without one. */
export function detailSourceOf(
  scene: Object3D,
): { file: string; meshes: Mesh[] } | null {
  const declared = new Map<string, Mesh[]>();
  scene.traverse((object) => {
    if (!(object instanceof Mesh) || Array.isArray(object.material)) {
      return;
    }
    const file: unknown = (object.material as Material).userData.detail;
    if (typeof file === "string" && file) {
      declared.set(file, [...(declared.get(file) ?? []), object]);
    }
  });
  const [first] = declared;
  return first ? { file: first[0], meshes: first[1] } : null;
}

/** Read a model's detail texture from beside its model.glb, sampled as a renderer does, with mipmaps. */
export async function loadDetail(
  model: string,
  source: { file: string; meshes: Mesh[] },
): Promise<Detail> {
  const file = await readModelFile(model, source.file);
  const bytes = Uint8Array.from(atob(file.base64), (character) =>
    character.charCodeAt(0),
  );
  // Its values are amounts, not colors, so nothing may convert them.
  const bitmap = await createImageBitmap(
    new Blob([bytes], { type: file.mimeType }),
    { colorSpaceConversion: "none", premultiplyAlpha: "none" },
  );
  const texture = new Texture(bitmap);
  // glTF's UVs run from the image's top left.
  texture.flipY = false;
  texture.magFilter = LinearFilter;
  texture.minFilter = LinearMipmapLinearFilter;
  texture.anisotropy = ANISOTROPY;
  texture.wrapS = ClampToEdgeWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return {
    file: source.file,
    texture,
    meshes: source.meshes,
    width: bitmap.width,
    height: bitmap.height,
    density: densityOf(source.meshes, bitmap.width, bitmap.height),
    uniforms: {
      detailMap: { value: texture },
      detailOn: { value: 1 },
      detailAlone: { value: 0 },
    },
  };
}

function densityOf(
  meshes: Mesh[],
  width: number,
  height: number,
): number | null {
  const densities: number[] = [];
  const start = new Vector3();
  const end = new Vector3();
  for (const mesh of meshes) {
    const { position, uv1 } = mesh.geometry.attributes;
    if (!uv1) {
      continue;
    }
    mesh.updateWorldMatrix(true, false);
    const index = mesh.geometry.index;
    const corners = index?.count ?? position.count;
    const vertex = (corner: number) => (index ? index.getX(corner) : corner);
    for (let first = 0; first + 2 < corners; first += 3) {
      for (let edge = 0; edge < 3; edge += 1) {
        const from = vertex(first + edge);
        const to = vertex(first + ((edge + 1) % 3));
        const texels = Math.hypot(
          (uv1.getX(to) - uv1.getX(from)) * width,
          (uv1.getY(to) - uv1.getY(from)) * height,
        );
        if (texels < MEASURED_TEXELS) {
          continue;
        }
        start
          .fromBufferAttribute(position, from)
          .applyMatrix4(mesh.matrixWorld);
        end.fromBufferAttribute(position, to).applyMatrix4(mesh.matrixWorld);
        const meters = start.distanceTo(end);
        if (meters > 0) {
          densities.push(texels / meters);
        }
      }
    }
  }
  if (densities.length === 0) {
    return null;
  }
  densities.sort((one, other) => one - other);
  return densities[Math.floor(densities.length / 2)];
}

/**
 * While the model is in view, shade the meshes `detail` covers with it as a renderer does, their base color times twice
 * it, showing the `layers` asked for. Call it before the scene is disposed of, so each material is put back first.
 */
export function useDetailView(detail: Detail | null, layers: Layers): void {
  useEffect(() => {
    if (detail) {
      return shadeMeshes(detail);
    }
  }, [detail]);
  useEffect(() => {
    if (detail) {
      show(detail, layers);
    }
  }, [detail, layers]);
}

function shadeMeshes(detail: Detail): () => void {
  const materials = new Set(
    detail.meshes.map((mesh) => mesh.material as Material),
  );
  const restores = [...materials].map((material) =>
    shadeWith(material, detail),
  );
  return () => {
    for (const restore of restores) {
      restore();
    }
    releaseDetail(detail);
  };
}

/** Free what a detail holds on the graphics card and in memory. */
export function releaseDetail(detail: Detail): void {
  detail.texture.dispose();
  (detail.texture.image as ImageBitmap).close();
}

function show(detail: Detail, layers: Layers): void {
  detail.uniforms.detailOn.value = layers === "colors" ? 0 : 1;
  detail.uniforms.detailAlone.value = layers === "detail" ? 1 : 0;
}

/** Shade a material by the detail as a renderer does, and return what puts it back as it was. */
export function shadeWith(material: Material, detail: Detail): () => void {
  const { onBeforeCompile, customProgramCacheKey } = material;
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, detail.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("void main() {", `${VERTEX}\nvoid main() {`)
      .replace(
        "#include <uv_vertex>",
        "#include <uv_vertex>\nvDetailUv = uv1;",
      );
    shader.fragmentShader = shader.fragmentShader
      .replace("void main() {", `${FRAGMENT}\nvoid main() {`)
      .replace("#include <map_fragment>", `#include <map_fragment>\n${SHADING}`)
      // Alone, the detail shows without the glow over it.
      .replace(
        "#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\ntotalEmissiveRadiance *= 1.0 - detailAlone;",
      );
  };
  material.customProgramCacheKey = () => PROGRAM;
  material.needsUpdate = true;
  return () => {
    material.onBeforeCompile = onBeforeCompile;
    material.customProgramCacheKey = customProgramCacheKey;
    material.needsUpdate = true;
  };
}
