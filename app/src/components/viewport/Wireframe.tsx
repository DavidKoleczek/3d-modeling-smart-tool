import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  type Object3D,
} from "three";

// Edges between faces that meet at less than this many degrees are left out, so a smooth surface stays quiet.
const CREASE_DEGREES = 20;

/** Put each mesh's edges where the mesh is now, and show them only while it shows. */
function follow(meshes: [LineSegments, Mesh][]) {
  for (const [lines, mesh] of meshes) {
    lines.matrix.copy(mesh.matrixWorld);
    // A part hidden on its own may be a group holding the mesh.
    let shown = mesh.visible;
    mesh.traverseAncestors((ancestor) => {
      shown &&= ancestor.visible;
    });
    lines.visible = shown;
  }
}

/** The model's mesh edges in accent ink, drawn over its shaded faces, following each part as the rig view poses it. */
export function Wireframe({
  scene,
  color,
}: {
  scene: Object3D;
  color: string;
}) {
  const edges = useMemo(() => {
    const material = new LineBasicMaterial({ color });
    const group = new Group();
    const meshes: [LineSegments, Mesh][] = [];
    scene.traverse((object) => {
      if (object instanceof Mesh) {
        const lines = new LineSegments(
          new EdgesGeometry(object.geometry, CREASE_DEGREES),
          material,
        );
        lines.matrixAutoUpdate = false;
        group.add(lines);
        meshes.push([lines, object]);
      }
    });
    return { group, material, meshes };
  }, [scene, color]);

  useFrame(() => follow(edges.meshes));

  useEffect(
    () => () => {
      for (const child of edges.group.children) {
        (child as LineSegments).geometry.dispose();
      }
      edges.material.dispose();
    },
    [edges],
  );

  return <primitive object={edges.group} />;
}
