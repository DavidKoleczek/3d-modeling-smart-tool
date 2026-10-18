import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, type RefObject } from "react";
import { Quaternion, Vector3 } from "three";

export type Axis = "x" | "y" | "z";
export type GizmoApi = { look: (axis: Axis) => void };

/** What the viewport needs of drei's OrbitControls, which `makeDefault` puts in the store untyped. */
type Orbit = { target: Vector3; update: () => void };

const AXES: Axis[] = ["x", "y", "z"];
const DIRECTIONS: Record<Axis, Vector3> = {
  x: new Vector3(1, 0, 0),
  y: new Vector3(0, 1, 0),
  z: new Vector3(0, 0, 1),
};
const SIZE = 76;
const CENTER = SIZE / 2;
const REACH = SIZE / 2 - 12;
// Straight down the camera's up axis has no orientation, so looking along Y leans off it this little.
const LEAN = new Vector3(0, 0, 1e-4);
const inverse = new Quaternion();
const facing = new Vector3();

/**
 * Inside the canvas: moves the gizmo's axes to match the camera each frame, and gives it `look`, which turns the camera
 * to look along an axis, or along its other side when it already does.
 */
export function GizmoDriver({
  svgRef,
  apiRef,
  movedRef,
}: {
  svgRef: RefObject<SVGSVGElement | null>;
  apiRef: RefObject<GizmoApi | null>;
  movedRef: RefObject<boolean>;
}) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as Orbit | null;

  useEffect(() => {
    apiRef.current = {
      look: (axis) => {
        const target = controls?.target ?? new Vector3();
        const distance = camera.position.distanceTo(target);
        const toward = DIRECTIONS[axis].clone();
        const now = camera.position.clone().sub(target).normalize();
        if (now.dot(toward) > 0.99) {
          toward.negate();
        }
        if (axis === "y") {
          toward.add(LEAN).normalize();
        }
        camera.position.copy(target).addScaledVector(toward, distance);
        camera.lookAt(target);
        controls?.update();
        movedRef.current = true;
      },
    };
  }, [apiRef, camera, controls, movedRef]);

  useFrame(() => {
    const element = svgRef.current;
    if (!element) {
      return;
    }
    inverse.copy(camera.quaternion).invert();
    for (const axis of AXES) {
      facing.copy(DIRECTIONS[axis]).applyQuaternion(inverse);
      const x = CENTER + facing.x * REACH;
      const y = CENTER - facing.y * REACH;
      const group = element.querySelector<SVGGElement>(`[data-axis="${axis}"]`);
      if (!group) {
        continue;
      }
      group.querySelector("line")?.setAttribute("x2", String(x));
      group.querySelector("line")?.setAttribute("y2", String(y));
      group.querySelector("rect")?.setAttribute("x", String(x - 7));
      group.querySelector("rect")?.setAttribute("y", String(y - 7));
      group.querySelector("text")?.setAttribute("x", String(x));
      group.querySelector("text")?.setAttribute("y", String(y + 3.5));
      // Axes pointing away from the camera recede, so the near ones read first.
      group.style.opacity = facing.z < -0.2 ? "0.45" : "1";
    }
  });

  return null;
}

/** The monochrome axis gizmo in the viewport's corner; clicking an axis looks along it. */
export function AxisGizmo({
  svgRef,
  onAxis,
}: {
  svgRef: RefObject<SVGSVGElement | null>;
  onAxis: (axis: Axis) => void;
}) {
  return (
    <svg
      ref={svgRef}
      width={SIZE}
      height={SIZE}
      role="group"
      aria-label="Axes"
      className="absolute right-3 bottom-3 z-10 overflow-visible"
    >
      {AXES.map((axis) => (
        <g
          key={axis}
          data-axis={axis}
          role="button"
          tabIndex={0}
          aria-label={`Look along ${axis.toUpperCase()}`}
          onClick={() => onAxis(axis)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onAxis(axis);
            }
          }}
          className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-(--ink) [&:hover>rect]:stroke-(--ink)"
        >
          <line
            x1={CENTER}
            y1={CENTER}
            x2={CENTER}
            y2={CENTER}
            stroke="var(--line-control)"
            strokeWidth={1.5}
          />
          <rect
            x={CENTER - 7}
            y={CENTER - 7}
            width={14}
            height={14}
            fill="var(--panel)"
            stroke="var(--line-control)"
          />
          <text
            x={CENTER}
            y={CENTER + 3.5}
            textAnchor="middle"
            fill="var(--ink)"
            className="pointer-events-none font-mono text-[10px] font-medium select-none"
          >
            {axis.toUpperCase()}
          </text>
        </g>
      ))}
      <rect
        x={CENTER - 2}
        y={CENTER - 2}
        width={4}
        height={4}
        fill="var(--ink-muted)"
      />
    </svg>
  );
}
