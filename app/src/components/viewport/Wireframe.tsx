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

/** The model's mesh edges in accent ink, drawn over its shaded faces. */
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
    scene.updateMatrixWorld(true);
    scene.traverse((object) => {
      if (object instanceof Mesh) {
        const lines = new LineSegments(
          new EdgesGeometry(object.geometry, CREASE_DEGREES),
          material,
        );
        lines.matrixAutoUpdate = false;
        lines.matrix.copy(object.matrixWorld);
        group.add(lines);
      }
    });
    return { group, material };
  }, [scene, color]);

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
