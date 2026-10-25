import { Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import { Box3, Vector3, type Group, type Object3D } from "three";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { swapKey, unitOf, type Motion, type Pose, type Rig } from "@/lib/rig";
import { counted } from "@/lib/stats";

type Point = [number, number, number];

// A marker's axes, and the line through a turning part's pivot along its axis, as a share of the model's size.
const MARKER_SIZE = 0.06;
const AXIS_SIZE = 0.12;
// The steps a slider moves a motion through across its range.
const SLIDER_STEPS = 200;
// A swap group's pick that shows every part of it, as the model was built.
const AS_BUILT = "as-built";
const unscaled = new Vector3();

/**
 * Its children where `target` is in the world each frame, as the parts it hangs from move, and hidden while `target`
 * is. Scaled with it, so points in `target`'s own space land right, or not, so a marker's axes keep their size.
 */
function Following({
  target,
  scaled,
  children,
}: {
  target: Object3D;
  scaled: boolean;
  children: ReactNode;
}) {
  const group = useRef<Group>(null);
  useFrame(() => {
    const following = group.current;
    if (!following) {
      return;
    }
    target.updateWorldMatrix(true, false);
    // A hidden bone is shrunk to nothing, which leaves no position or rotation to follow.
    let shown = target.visible && target.matrixWorld.determinant() !== 0;
    target.traverseAncestors((ancestor) => {
      shown &&= ancestor.visible;
    });
    following.visible = shown;
    if (!shown) {
      return;
    }
    target.matrixWorld.decompose(
      following.position,
      following.quaternion,
      scaled ? following.scale : unscaled,
    );
  });
  return <group ref={group}>{children}</group>;
}

function Label({ position, children }: { position: Point; children: string }) {
  return (
    <Html
      position={position}
      zIndexRange={[5, 0]}
      className="pointer-events-none"
    >
      <span className="ml-1.5 bg-canvas px-1 mono-annotation whitespace-nowrap text-accent-ink">
        {children}
      </span>
    </Html>
  );
}

/** Where a slide or turn is: the path a slide travels, or its axis through the pivot, in the parent's space. */
function MotionPath({
  motion,
  rest,
  size,
  color,
}: {
  motion: Extract<Motion, { axis: Vector3 }>;
  rest: Vector3;
  size: number;
  color: string;
}) {
  const [from, to] =
    motion.kind === "slide" ? motion.range : [-size / 2, size / 2];
  const ends = [from, to].map(
    (along): Point =>
      rest.clone().addScaledVector(motion.axis, along).toArray() as Point,
  );
  return (
    <Line
      points={ends}
      color={color}
      lineWidth={1}
      dashed
      dashSize={size / 20}
      gapSize={size / 30}
      depthTest={false}
      renderOrder={10}
    />
  );
}

/**
 * Inside the canvas: each marker as its axes and name, longest along its +Z, which the check reports it facing; and
 * each part that slides or turns as its name at its pivot, with the path it slides or the axis it turns about.
 */
export function RigOverlay({
  rig,
  scene,
  color,
}: {
  rig: Rig;
  scene: Object3D;
  color: string;
}) {
  const reach = useMemo(() => {
    const size = new Box3().setFromObject(scene).getSize(new Vector3());
    return Math.max(size.x, size.y, size.z) || 1;
  }, [scene]);
  const marker = reach * MARKER_SIZE;
  const common = { color, depthTest: false, renderOrder: 10 };
  return (
    <group userData={{ inStills: false }}>
      {rig.markers.map((each) => (
        <Following key={each.uuid} target={each} scaled={false}>
          <Line
            points={[
              [0, 0, 0],
              [marker, 0, 0],
            ]}
            lineWidth={1}
            {...common}
          />
          <Line
            points={[
              [0, 0, 0],
              [0, marker, 0],
            ]}
            lineWidth={1}
            {...common}
          />
          <Line
            points={[
              [0, 0, 0],
              [0, 0, marker * 2],
            ]}
            lineWidth={2}
            {...common}
          />
          <Label position={[0, 0, 0]}>{each.name}</Label>
        </Following>
      ))}
      {rig.motions.map((motion) => {
        const rest = rig.rest.get(motion.part);
        if (!rest || !("axis" in motion) || !motion.part.parent) {
          return null;
        }
        return (
          <Following key={motion.part.uuid} target={motion.part.parent} scaled>
            <MotionPath
              motion={motion}
              rest={rest.position}
              size={reach * AXIS_SIZE}
              color={color}
            />
          </Following>
        );
      })}
      {rig.motions.map(
        (motion) =>
          "axis" in motion && (
            <Following
              key={`${motion.part.uuid}-pivot`}
              target={motion.part}
              scaled={false}
            >
              <Label position={[0, 0, 0]}>{motion.part.name}</Label>
            </Following>
          ),
      )}
    </group>
  );
}

function formatted(value: number, motion: Motion): string {
  return motion.kind === "slide"
    ? `${Number(value.toFixed(3))} ${unitOf(motion)}`
    : `${Math.round(value)} ${unitOf(motion)}`;
}

/** A slide, hinge, or spin, with a slider across its range. */
function RangeRow({
  motion,
  pose,
  onPose,
}: {
  motion: Extract<Motion, { axis: Vector3 }>;
  pose: Pose;
  onPose: (pose: Pose) => void;
}) {
  const [low, high] = motion.range;
  const set = pose[motion.part.uuid];
  // At rest is 0 along a motion, which a range may leave out.
  const value =
    typeof set === "number" ? set : Math.min(Math.max(0, low), high);
  return (
    <li className="flex flex-col gap-1 border-t border-line px-2.5 py-2 first:border-t-0">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="truncate mono-value">{motion.part.name}</span>
        <span className="mono-annotation text-ink-muted">{motion.kind}</span>
        <span className="ml-auto shrink-0 mono-annotation text-ink-muted">
          {typeof set === "number" ? formatted(set, motion) : "at rest"}
        </span>
      </div>
      <input
        type="range"
        min={low}
        max={high}
        step={(high - low) / SLIDER_STEPS || 1}
        value={value}
        onChange={(event) =>
          onPose({ ...pose, [motion.part.uuid]: Number(event.target.value) })
        }
        aria-label={`${motion.part.name}, ${motion.kind} from ${formatted(low, motion)} to ${formatted(high, motion)}`}
        className="w-full accent-(--accent)"
      />
    </li>
  );
}

/**
 * Beside the 3D view: a slider for each slide, hinge, and spin over its range, a switch for each part that can be
 * hidden, and a pick of the part each swap group shows, which pose the model in view. At rest puts it back.
 */
export function RigPanel({
  rig,
  pose,
  onPose,
}: {
  rig: Rig;
  pose: Pose;
  onPose: (pose: Pose) => void;
}) {
  const groups = new Map<string, Object3D[]>();
  for (const motion of rig.motions) {
    if (motion.kind === "swap") {
      groups.set(motion.group, [
        ...(groups.get(motion.group) ?? []),
        motion.part,
      ]);
    }
  }
  const empty = rig.motions.length === 0 && rig.markers.length === 0;
  return (
    <aside
      aria-label="Rig"
      className="flex min-h-0 flex-col overflow-hidden rounded-md border border-line bg-panel"
    >
      <header className="shrink-0 border-b border-line px-2.5 py-1.5">
        <div className="flex h-6 items-center gap-1.5 text-label">
          <Icon name="rig" />
          Rig
          <span className="flex-1" />
          {Object.keys(pose).length > 0 && (
            <Button size="sm" onClick={() => onPose({})}>
              At rest
            </Button>
          )}
        </div>
        <p className="mono-annotation text-ink-muted">
          {counted(rig.motions.length, "motion", "motions")} ·{" "}
          {counted(rig.markers.length, "marker", "markers")}
        </p>
      </header>
      <div className="min-h-0 overflow-y-auto">
        <ol>
          {rig.motions.map((motion) =>
            "axis" in motion ? (
              <RangeRow
                key={motion.part.uuid}
                motion={motion}
                pose={pose}
                onPose={onPose}
              />
            ) : (
              motion.kind === "hide" && (
                <li
                  key={motion.part.uuid}
                  className="flex min-w-0 items-center gap-2 border-t border-line px-2.5 py-2 first:border-t-0"
                >
                  <span className="truncate mono-value">
                    {motion.part.name}
                  </span>
                  <span className="flex-1" />
                  <Switch
                    checked={pose[motion.part.uuid] !== true}
                    onChange={(shown) =>
                      onPose({ ...pose, [motion.part.uuid]: !shown })
                    }
                  >
                    Shown
                  </Switch>
                </li>
              )
            ),
          )}
          {[...groups].map(([group, parts]) => {
            const shown = pose[swapKey(group)];
            return (
              <li
                key={group}
                className="flex flex-col gap-1 border-t border-line px-2.5 py-2 first:border-t-0"
              >
                <span className="mono-annotation text-ink-muted">
                  Swap group {group}
                </span>
                <Select
                  label={`Part swap group ${group} shows`}
                  value={typeof shown === "string" ? shown : AS_BUILT}
                  onChange={(picked) => {
                    const next = { ...pose, [swapKey(group)]: picked };
                    if (picked === AS_BUILT) {
                      delete next[swapKey(group)];
                    }
                    onPose(next);
                  }}
                  items={[
                    { value: AS_BUILT, label: "All, as built" },
                    ...parts.map((part) => ({
                      value: part.uuid,
                      label: part.name,
                    })),
                  ]}
                />
              </li>
            );
          })}
        </ol>
        {empty && (
          <p className="px-2.5 py-2 text-ink-muted">
            Nothing declares a motion, and there are no markers. Rig the model
            to give its moving parts their motions.
          </p>
        )}
        {rig.malformed.length > 0 && (
          <p className="border-t border-line px-2.5 py-2 text-caption text-ink-muted">
            {rig.malformed.map((part) => part.name).join(", ")}{" "}
            {rig.malformed.length === 1 ? "declares" : "declare"} a motion that
            isn't well formed. Checks says why.
          </p>
        )}
      </div>
    </aside>
  );
}
