import { Box3, Mesh, Vector3, type Material, type Object3D } from "three";

/** What a loaded model is made of, and how big it is, for display only. */
export type SceneStats = {
  triangles: number;
  meshes: number;
  materials: number;
  /** In meters, as glTF's units are. */
  size: Vector3;
};

export function sceneStats(scene: Object3D): SceneStats {
  let triangles = 0;
  let meshes = 0;
  const materials = new Set<Material>();
  scene.traverse((object) => {
    if (!(object instanceof Mesh)) {
      return;
    }
    meshes += 1;
    const geometry = object.geometry;
    const count = geometry.index?.count ?? geometry.attributes.position?.count;
    triangles += Math.floor((count ?? 0) / 3);
    for (const material of [object.material].flat()) {
      materials.add(material);
    }
  });
  const size = new Box3().setFromObject(scene).getSize(new Vector3());
  return { triangles, meshes, materials: materials.size, size };
}

/** A length in meters as the app shows one, such as "0.42 m" or "0.074 m". */
export function meters(value: number): string {
  return `${value >= 1 ? value.toFixed(2) : Number(value.toPrecision(2))} m`;
}

/** A size as width by height by depth, such as "0.42 × 0.61 × 0.38 m". */
export function dimensions(size: Vector3): string {
  const each = [size.x, size.y, size.z].map((value) =>
    meters(value).replace(" m", ""),
  );
  return `${each.join(" × ")} m`;
}

const count = new Intl.NumberFormat();

/** A count with its unit, such as "1,248 tris" or "1 mesh". */
export function counted(value: number, one: string, many: string): string {
  return `${count.format(value)} ${value === 1 ? one : many}`;
}
