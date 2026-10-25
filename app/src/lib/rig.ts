import { Quaternion, Vector3, type Bone, type Object3D } from "three";

/**
 * A part's motion, as the check reads it from the `motion` in its glTF extras, which three.js loads into `userData`.
 * The axis is in the part's parent's space, through the part's origin, which is its pivot. A slide's range is in
 * meters, a hinge's in degrees, and a spin goes all the way around.
 */
export type Motion =
  | {
      kind: "slide" | "hinge" | "spin";
      part: Object3D;
      axis: Vector3;
      range: [number, number];
    }
  | { kind: "hide"; part: Object3D }
  | { kind: "swap"; part: Object3D; group: string };

/** Where the person set each motion, by its part's id: along a range, or hidden; and by `swap:<group>`, the part shown. */
export type Pose = Record<string, number | boolean | string>;

/** The rig of a loaded model: its motions, the parts whose motion can't be read, and its markers. */
export type Rig = {
  motions: Motion[];
  malformed: Object3D[];
  markers: Object3D[];
  /** Each moving part as it was loaded, which every pose starts from. */
  rest: Map<
    Object3D,
    {
      position: Vector3;
      quaternion: Quaternion;
      scale: Vector3;
      visible: boolean;
    }
  >;
};

const SPIN: [number, number] = [0, 360];

/** The key a swap group's pick is under in a pose. */
export function swapKey(group: string): string {
  return `swap:${group}`;
}

function numbers(value: unknown, count: number): value is number[] {
  return (
    Array.isArray(value) &&
    value.length === count &&
    value.every((each) => typeof each === "number" && Number.isFinite(each))
  );
}

/** The motion `part` declares, or null when it is not well formed; JSON text of one reads as the object. */
function motionOf(part: Object3D, declared: unknown): Motion | null {
  let motion = declared;
  if (typeof motion === "string") {
    try {
      motion = JSON.parse(motion);
    } catch {
      return null;
    }
  }
  if (typeof motion !== "object" || motion === null) {
    return null;
  }
  const { kind, axis, range, group } = motion as Record<string, unknown>;
  if (kind === "hide") {
    return { kind, part };
  }
  if (kind === "swap") {
    return typeof group === "string" && group ? { kind, part, group } : null;
  }
  if (kind !== "slide" && kind !== "hinge" && kind !== "spin") {
    return null;
  }
  if (!numbers(axis, 3) || axis.every((each) => each === 0)) {
    return null;
  }
  const direction = new Vector3(axis[0], axis[1], axis[2]).normalize();
  if (kind === "spin") {
    return { kind, part, axis: direction, range: SPIN };
  }
  if (!numbers(range, 2) || range[0] > range[1]) {
    return null;
  }
  return { kind, part, axis: direction, range: [range[0], range[1]] };
}

/** The motions and markers in `scene`. Markers are empties with nothing under them, as the check finds them. */
export function rigOf(scene: Object3D): Rig {
  const rig: Rig = { motions: [], malformed: [], markers: [], rest: new Map() };
  scene.traverse((object) => {
    const declared: unknown = object.userData.motion;
    if (declared !== undefined && declared !== null) {
      const motion = motionOf(object, declared);
      if (motion) {
        rig.motions.push(motion);
        rig.rest.set(object, {
          position: object.position.clone(),
          quaternion: object.quaternion.clone(),
          scale: object.scale.clone(),
          visible: object.visible,
        });
      } else {
        rig.malformed.push(object);
      }
    }
    // Bones load as their own type, and meshes, cameras, and lights as theirs.
    if (
      object !== scene &&
      object.type === "Object3D" &&
      object.children.length === 0
    ) {
      rig.markers.push(object);
    }
  });
  return rig;
}

/** Move each part of `rig` to where `values` set it, from where it rests; what `values` leaves out stays at rest. */
export function pose(rig: Rig, values: Pose): void {
  for (const motion of rig.motions) {
    const { part } = motion;
    const rest = rig.rest.get(part);
    if (!rest) {
      continue;
    }
    part.position.copy(rest.position);
    part.quaternion.copy(rest.quaternion);
    part.scale.copy(rest.scale);
    part.visible = rest.visible;
    const value = values[part.uuid];
    switch (motion.kind) {
      case "slide":
        if (typeof value === "number") {
          part.position.addScaledVector(motion.axis, value);
        }
        break;
      case "hinge":
      case "spin":
        if (typeof value === "number") {
          // About an axis in the parent's space, so the turn comes after the part's own rotation at rest.
          part.quaternion.premultiply(
            new Quaternion().setFromAxisAngle(
              motion.axis,
              (value * Math.PI) / 180,
            ),
          );
        }
        break;
      case "hide":
        if (value === true) {
          hide(part);
        }
        break;
      case "swap": {
        const shown = values[swapKey(motion.group)];
        if (typeof shown === "string" && shown !== part.uuid) {
          hide(part);
        }
        break;
      }
    }
  }
}

/**
 * Hide a part and what hangs from it. A bone's vertices are drawn with the mesh skinned to it whatever the bone's own
 * visibility, so a bone shrinks to nothing instead.
 */
function hide(part: Object3D): void {
  if ((part as Bone).isBone) {
    part.scale.setScalar(0);
  } else {
    part.visible = false;
  }
}

/** The units a motion's range is in, as the app shows them. */
export function unitOf(motion: Motion): string {
  return motion.kind === "slide" ? "m" : "deg";
}
