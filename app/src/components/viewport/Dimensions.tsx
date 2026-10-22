import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import { Box3, Vector3, type Object3D } from "three";

import { meters } from "@/lib/stats";

type Point = [number, number, number];

/** One dimension line between `from` and `to`, with extension lines back to the model and its length midway. */
function Measure({
  from,
  to,
  out,
  length,
  color,
}: {
  from: Point;
  to: Point;
  /** Where the extension lines start, back toward the model, from each end. */
  out: Point;
  length: number;
  color: string;
}) {
  const ends = [from, to].map((point): Point => [
    point[0] - out[0],
    point[1] - out[1],
    point[2] - out[2],
  ]);
  const middle: Point = [
    (from[0] + to[0]) / 2,
    (from[1] + to[1]) / 2,
    (from[2] + to[2]) / 2,
  ];
  const common = { color, lineWidth: 1, depthTest: false, renderOrder: 10 };
  return (
    <>
      <Line points={[from, to]} {...common} />
      <Line points={[ends[0], from]} {...common} />
      <Line points={[ends[1], to]} {...common} />
      <Html
        center
        position={middle}
        zIndexRange={[5, 0]}
        className="pointer-events-none"
      >
        <span className="bg-canvas px-1 mono-annotation whitespace-nowrap text-accent-ink">
          {meters(length)}
        </span>
      </Html>
    </>
  );
}

/** Dimension lines on the model's bounds, width along the front, height up its left, and depth along its right. */
export function Dimensions({
  scene,
  color,
}: {
  scene: Object3D;
  color: string;
}) {
  const box = useMemo(() => new Box3().setFromObject(scene), [scene]);
  const size = box.getSize(new Vector3());
  const gap = Math.max(size.x, size.y, size.z) * 0.08;
  const { min, max } = box;
  return (
    <group userData={{ inStills: false }}>
      <Measure
        from={[min.x, min.y, max.z + gap]}
        to={[max.x, min.y, max.z + gap]}
        out={[0, 0, gap]}
        length={size.x}
        color={color}
      />
      <Measure
        from={[min.x - gap, min.y, max.z]}
        to={[min.x - gap, max.y, max.z]}
        out={[-gap, 0, 0]}
        length={size.y}
        color={color}
      />
      <Measure
        from={[max.x + gap, min.y, min.z]}
        to={[max.x + gap, min.y, max.z]}
        out={[gap, 0, 0]}
        length={size.z}
        color={color}
      />
    </group>
  );
}
