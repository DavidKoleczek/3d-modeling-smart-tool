import { ContactShadows, Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import {
  Box3,
  MOUSE,
  PerspectiveCamera,
  type Camera,
  PMREMGenerator,
  Sphere,
  Vector3,
  type Mesh,
  type Object3D,
} from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Notice } from "@/components/ui/notice";
import { ProgressBar } from "@/components/ui/progress-bar";
import {
  AxisGizmo,
  GizmoDriver,
  type GizmoApi,
} from "@/components/viewport/AxisGizmo";
import { Checks } from "@/components/viewport/Checks";
import { Dimensions } from "@/components/viewport/Dimensions";
import {
  CaptureDriver,
  Markup,
  type CaptureApi,
} from "@/components/viewport/Markup";
import { Renders } from "@/components/viewport/Renders";
import { RigOverlay, RigPanel } from "@/components/viewport/Rig";
import { SurfacePanel } from "@/components/viewport/Surface";
import {
  ViewportToolbar,
  type ViewTool,
} from "@/components/viewport/ViewportToolbar";
import { Wireframe } from "@/components/viewport/Wireframe";
import {
  GLB,
  readModelFile,
  type ModelListing,
  type ModelMode,
  type ModelSummary,
} from "@/lib/api";
import {
  detailSourceOf,
  loadDetail,
  releaseDetail,
  useDetailView,
  type Detail,
  type Layers,
} from "@/lib/detail";
import { describe } from "@/lib/errors";
import { NO_MARKUP, type Markup as MarkupDraft } from "@/lib/markup";
import { pastelFor } from "@/lib/models";
import {
  cellAt,
  intersectionUv,
  paletteOf,
  useColorView,
  type Look,
  type Palette,
} from "@/lib/palette";
import { pose, rigOf, type Pose } from "@/lib/rig";
import { dispose, parseGlb } from "@/lib/scene";
import { updateSettings, useSettings } from "@/lib/settings";
import { sceneStats, type SceneStats } from "@/lib/stats";
import { timeOfDay, useDelayed, useElapsed } from "@/lib/time";
import { useTheme } from "@/lib/theme";
import { useSceneColors } from "@/lib/tokens";
import { cn } from "@/lib/utils";

export type ViewMode = "3d" | "renders" | "checks";

/** The model's scene as loaded, from the build at `built`; `rebuilt` once it replaced an earlier build in view. */
type Shown = { name: string; scene: Object3D; built: string; rebuilt: boolean };

/** What the viewport needs of drei's OrbitControls, which `makeDefault` puts in the store untyped. */
type Orbit = {
  target: Vector3;
  update: () => void;
  addEventListener: (type: "start", listener: () => void) => void;
  removeEventListener: (type: "start", listener: () => void) => void;
};

// Three quarters from the front and above, the way the agent's renders usually look at a model.
const VIEW_DIRECTION = new Vector3(0.8, 0.55, 1).normalize();
const MARGIN = 1.1;
// Every button turns the model, and OrbitControls pans any of them held with shift.
const MOUSE_BUTTONS = {
  LEFT: MOUSE.ROTATE,
  MIDDLE: MOUSE.ROTATE,
  RIGHT: MOUSE.ROTATE,
};
const AT_REST: Pose = {};

/** Points the camera at the whole model from the three-quarter view, unless the person moved it and `force` is off. */
function frame(
  scene: Object3D,
  camera: Camera,
  controls: Orbit | null,
  movedRef: RefObject<boolean>,
  force: boolean,
) {
  const sphere = new Box3()
    .setFromObject(scene)
    .getBoundingSphere(new Sphere());
  const inside =
    camera.position.distanceTo(sphere.center) < sphere.radius * MARGIN;
  if (
    (!force && movedRef.current && !inside) ||
    !(camera instanceof PerspectiveCamera)
  ) {
    return;
  }
  // Whichever field of view is narrower decides, so the model fits a tall viewport as well as a wide one.
  const vertical = (camera.fov * Math.PI) / 180;
  const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
  const distance =
    (sphere.radius * MARGIN) / Math.sin(Math.min(vertical, horizontal) / 2);
  camera.position.copy(sphere.center).addScaledVector(VIEW_DIRECTION, distance);
  camera.lookAt(sphere.center);
  controls?.target.copy(sphere.center);
  controls?.update();
  movedRef.current = false;
}

/**
 * Frames the model when it is first shown, and again on each rebuild unless the person has moved the camera since,
 * or the rebuilt model would swallow the camera. Each new `fit` frames it whatever the camera did.
 */
function Framing({
  scene,
  movedRef,
  fit,
}: {
  scene: Object3D;
  movedRef: RefObject<boolean>;
  fit: number;
}) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as Orbit | null;
  const fitted = useRef(fit);

  useEffect(() => {
    if (!controls) {
      return;
    }
    const onStart = () => {
      movedRef.current = true;
    };
    controls.addEventListener("start", onStart);
    return () => controls.removeEventListener("start", onStart);
  }, [controls, movedRef]);

  useLayoutEffect(() => {
    const force = fitted.current !== fit;
    fitted.current = fit;
    frame(scene, camera, controls, movedRef, force);
  }, [scene, camera, controls, movedRef, fit]);

  return null;
}

/** Image based lighting generated in place, since the view's CSP refuses the HDR files lighting usually loads. */
function RoomLighting() {
  const gl = useThree((state) => state.gl);
  const environment = useMemo(() => {
    const generator = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const texture = generator.fromScene(room, 0.04).texture;
    room.dispose();
    generator.dispose();
    return texture;
  }, [gl]);

  useEffect(() => () => environment.dispose(), [environment]);

  return <primitive object={environment} attach="environment" />;
}

/** The floor under the model: a grid scaled to its size, and a soft contact shadow that grounds it. */
function Floor({
  scene,
  grid,
  cell,
  section,
  shadow,
  dark,
}: {
  scene: Object3D;
  grid: boolean;
  cell: string;
  section: string;
  shadow: string;
  dark: boolean;
}) {
  const { base, center, reach } = useMemo(() => {
    const box = new Box3().setFromObject(scene);
    const size = box.getSize(new Vector3());
    return {
      base: box.min.y,
      center: box.getCenter(new Vector3()),
      reach: Math.max(size.x, size.y, size.z) || 1,
    };
  }, [scene]);
  // Sections a power of ten near the model's size, and cells a tenth of that.
  const step = 10 ** Math.floor(Math.log10(reach));
  return (
    <>
      {/* Its frame count starts over each time it renders, so a new name draws the rebuilt model's shadow. Remounting
          it would too, but leave its render targets on the GPU, since it never frees them. */}
      <ContactShadows
        name={scene.uuid}
        position={[center.x, base + reach * 0.001, center.z]}
        scale={reach * 3}
        far={reach}
        blur={2.5}
        opacity={dark ? 0.6 : 0.35}
        resolution={512}
        frames={1}
        color={shadow}
      />
      {grid && (
        <Grid
          position={[0, base, 0]}
          infiniteGrid
          cellSize={step / 10}
          sectionSize={step}
          fadeDistance={reach * 25}
          cellColor={cell}
          sectionColor={section}
        />
      )}
    </>
  );
}

function Elapsed({ since }: { since: string }) {
  return <>{useElapsed(since)}</>;
}

/**
 * The model in view in 3D, reloaded each time its GLB is rebuilt, with its tools, or the renders the agent made of it,
 * or its latest check. The rig view poses it through the motions its parts declare, and the surface view shows its
 * colors and detail, its palette's roles in each scheme, and colors to try. A detail texture its materials declare
 * shades it as a renderer would, whichever view is on. `onStats` hears what the loaded model is made of.
 */
export function Viewport({
  listing,
  model,
  mode,
  onMode,
  compact,
  fit,
  onFit,
  onStats,
  onNew,
  onCompose,
}: {
  listing: ModelListing | null;
  model: ModelSummary | null;
  mode: ViewMode;
  onMode: (mode: ViewMode) => void;
  /** Where the top bar has no room for the 3D, Renders, and Checks switch, so the toolbar holds it. */
  compact: boolean;
  fit: number;
  onFit: () => void;
  onStats: (stats: SceneStats | null) => void;
  onNew: () => void;
  /** Put marked views and their notes, or colors tried, in the model's message to its agent, to send from there. */
  onCompose: (text: string, files: File[], mode?: ModelMode) => void;
}) {
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState<{ name: string; text: string } | null>(
    null,
  );
  const { settings } = useSettings();
  const colors = useSceneColors();
  const dark = useTheme() === "dark";
  const moved = useRef(false);
  const gizmo = useRef<SVGSVGElement>(null);
  const look = useRef<GizmoApi | null>(null);
  const capture = useRef<CaptureApi | null>(null);
  // By model, what the person is marking up, which outlasts looking at another model or the renders for a while.
  const [markups, setMarkups] = useState<Record<string, MarkupDraft>>({});
  const name = model?.name;
  const built = model?.built;

  useEffect(() => {
    if (!name || !built) {
      return;
    }
    let current = true;
    readModelFile(name, GLB)
      .then((file) => parseGlb(file.base64))
      .then(
        (scene) => {
          if (current) {
            setShown((before) => ({
              name,
              scene,
              built,
              rebuilt: before?.name === name,
            }));
            setError(null);
          } else {
            dispose(scene);
          }
        },
        (cause) => {
          if (current) {
            setError({ name, text: describe(cause) });
          }
        },
      );
    return () => {
      current = false;
    };
  }, [name, built]);

  const scene = shown?.scene;

  const showing = shown !== null && shown.name === name;
  const failure = error !== null && error.name === name ? error.text : null;
  const loading = useDelayed(Boolean(model?.built) && !showing && !failure);
  const looking = useDelayed(listing === null);

  useEffect(
    () => onStats(showing && scene ? sceneStats(scene) : null),
    [showing, scene, onStats],
  );

  const toggle = (tool: ViewTool) =>
    updateSettings((current) => ({ ...current, [tool]: !current[tool] }));

  const in3d = mode === "3d";
  const markup = (name && markups[name]) || NO_MARKUP;
  const locked = in3d && markup.viewing !== null;

  // Where the person set each motion of the scene in view; a new build starts at rest.
  const [posed, setPosed] = useState<{ scene: Object3D; pose: Pose } | null>(
    null,
  );
  const rig = useMemo(() => (scene ? rigOf(scene) : null), [scene]);
  const rigging = settings.rig && in3d && showing;
  const posing = posed !== null && posed.scene === scene ? posed.pose : AT_REST;
  useEffect(() => {
    if (rig) {
      pose(rig, rigging ? posing : AT_REST);
    }
  }, [rig, rigging, posing]);

  // The detail texture the scene in view declares, read from beside its model.glb.
  const shownName = shown?.name;
  const [loaded, setLoaded] = useState<{
    scene: Object3D;
    detail: Detail;
  } | null>(null);
  useEffect(() => {
    const source = scene ? detailSourceOf(scene) : null;
    if (!scene || !shownName || !source) {
      return;
    }
    let current = true;
    loadDetail(shownName, source).then(
      (found) => {
        if (current) {
          setLoaded({ scene, detail: found });
        } else {
          releaseDetail(found);
        }
      },
      // A texture the app can't read leaves the model without its detail, and the check says why.
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [scene, shownName]);
  const detail =
    loaded !== null && loaded.scene === scene ? loaded.detail : null;

  // The palette of the scene in view, read once the surface view is on, and how that view shows it, which starts in
  // the scheme the model was built in.
  const palette = useMemo(
    () => (scene && settings.surface ? paletteOf(scene) : null),
    [scene, settings.surface],
  );
  const surfacing =
    settings.surface &&
    in3d &&
    showing &&
    (palette !== null || detail !== null);
  const coloring = surfacing && palette !== null;
  const [layers, setLayers] = useState<Layers>("both");
  const asBuilt = useMemo<Look>(
    () => ({ scheme: palette?.row ?? 0, focus: null, tried: {} }),
    [palette],
  );
  const [looked, setLooked] = useState<{ palette: Palette; look: Look } | null>(
    null,
  );
  const colorLook =
    looked !== null && looked.palette === palette ? looked.look : asBuilt;
  const [flat, setFlat] = useState(false);
  const [pointed, setPointed] = useState<number | null>(null);
  const pointAt = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    const uv = palette && event[intersectionUv(palette)];
    const cell =
      palette && uv && palette.meshes.includes(event.object as Mesh)
        ? cellAt(palette, uv.x, uv.y)
        : null;
    setPointed(cell?.column ?? null);
  };
  useDetailView(detail, surfacing ? layers : "both");
  useColorView(palette, coloring, colorLook, flat, detail);
  // After the surface view, so every mesh has its own material back before the scene it was in is freed.
  useEffect(
    () => () => {
      if (scene) {
        dispose(scene);
      }
    },
    [scene],
  );

  // Forgets a model's markup once nothing is left in it.
  const changeMarkup = (change: (markup: MarkupDraft) => MarkupDraft) =>
    setMarkups((current) => {
      if (!name) {
        return current;
      }
      const next = { ...current };
      const after = change(current[name] ?? NO_MARKUP);
      if (after.snapshots.length || after.message || after.marking) {
        next[name] = after;
      } else {
        delete next[name];
      }
      return next;
    });

  let message: ReactNode = null;
  if (listing === null) {
    message = looking && (
      <div className="m-auto flex items-center gap-2 mono-annotation text-ink-muted">
        <LoadingMark size={12} />
        Looking for models
      </div>
    );
  } else if (listing.models.length === 0) {
    message = (
      <EmptyState
        className="flex-1"
        measure="0 models"
        tile={<Icon name="model" size={24} />}
        tileClassName="bg-pastel-blue"
        title="Start with a description"
        action={
          <>
            <Button
              variant="primary"
              size="lg"
              onClick={onNew}
              className="mt-2"
            >
              <Icon name="add" size={20} />
              New model
            </Button>
            <p className="text-caption text-ink-muted">
              Or ask your agent to make one.
            </p>
          </>
        }
      >
        Describe a model, add reference images if you have them, and watch it
        being built here.
      </EmptyState>
    );
  } else if (model === null) {
    message = (
      <EmptyState
        className="flex-1"
        tile={<Icon name="model" size={24} />}
        tileClassName="bg-pastel-stone"
        title="Pick a model"
      >
        Choose one of your models to see it here.
      </EmptyState>
    );
  } else if (!model.built) {
    message =
      model.status === "running" ? (
        <EmptyState
          className="flex-1"
          measure={
            <>
              Working ·{" "}
              <Elapsed since={model.last_run?.started ?? model.updated} />
            </>
          }
          tile={<Icon name="model" size={24} />}
          tileClassName={pastelFor(model.name)}
          title={`Building ${model.name}`}
        >
          It shows here as soon as the first version is built. Follow along in
          Activity.
        </EmptyState>
      ) : (
        <EmptyState
          className="flex-1"
          tile={<Icon name="model" size={24} />}
          tileClassName={pastelFor(model.name)}
          title={`${model.name} isn't built yet`}
        >
          {model.status === null
            ? "Describe it in Activity, and it shows here once the first version is built."
            : `Its last run ended before it made a ${GLB}. Ask for a change in Activity to try again.`}
        </EmptyState>
      );
  } else if (!showing) {
    message = failure ? (
      <EmptyState
        className="flex-1"
        tile={<Icon name="warning" size={24} />}
        tileClassName="bg-danger-soft text-danger"
        title={`Couldn't show ${model.name}`}
      >
        {failure}
      </EmptyState>
    ) : (
      loading && (
        <div className="m-auto flex items-center gap-2 mono-annotation text-ink-muted">
          <LoadingMark size={12} />
          Loading {model.name}
        </div>
      )
    );
  }

  return (
    <section
      aria-label="Viewport"
      className="relative flex h-full min-h-48 flex-1 overflow-hidden bg-canvas"
    >
      {model?.status === "running" && <ProgressBar className="z-20" />}
      {showing && model ? (
        <Markup
          model={model}
          onCompose={onCompose}
          active={in3d}
          tools={
            <ViewportToolbar
              on={{
                grid: settings.grid,
                wireframe: settings.wireframe,
                dimensions: settings.dimensions,
                rig: settings.rig,
                surface: settings.surface,
              }}
              onToggle={toggle}
              onFit={onFit}
              locked={locked}
              compact={compact}
              onRenders={compact ? () => onMode("renders") : undefined}
              onChecks={compact ? () => onMode("checks") : undefined}
            />
          }
          compact={compact}
          markup={markup}
          onChange={changeMarkup}
          capture={capture}
        >
          <Canvas
            camera={{ position: [2, 1.5, 2.5], fov: 45, near: 0.01, far: 1000 }}
            dpr={[1, 2]}
          >
            <RoomLighting />
            <directionalLight position={[3, 6, 4]} intensity={1.5} />
            {/* Keyed by model, so switching models frames the new one however the camera was left. */}
            <group key={shown.name}>
              <primitive
                object={shown.scene}
                onPointerMove={coloring ? pointAt : undefined}
                onPointerOut={coloring ? () => setPointed(null) : undefined}
              />
              <Framing scene={shown.scene} movedRef={moved} fit={fit} />
              {settings.wireframe && (
                <Wireframe scene={shown.scene} color={colors.accentInk} />
              )}
              {settings.dimensions && (
                <Dimensions scene={shown.scene} color={colors.accentInk} />
              )}
              {rigging && rig && (
                <RigOverlay
                  rig={rig}
                  scene={shown.scene}
                  color={colors.accentInk}
                />
              )}
              <Floor
                scene={shown.scene}
                grid={settings.grid}
                cell={colors.gridCell}
                section={colors.gridSection}
                shadow={colors.shadow}
                dark={dark}
              />
            </group>
            {/* Still while marking, so a drag draws a box rather than turning the model. */}
            <OrbitControls
              makeDefault
              enabled={!(in3d && markup.marking)}
              mouseButtons={MOUSE_BUTTONS}
            />
            <GizmoDriver svgRef={gizmo} apiRef={look} movedRef={moved} />
            <CaptureDriver apiRef={capture} />
          </Canvas>
        </Markup>
      ) : (
        message
      )}
      {showing && in3d && (
        <>
          {shown.rebuilt && !locked && (
            <div className="absolute top-3 right-3 z-10 flex h-7 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5">
              <Icon name="check" />
              <span className="mono-annotation text-ink">
                Rebuilt {timeOfDay(shown.built, true)}
              </span>
            </div>
          )}
          {!locked && (
            <AxisGizmo
              svgRef={gizmo}
              onAxis={(axis) => look.current?.look(axis)}
            />
          )}
          {!locked && ((rigging && rig) || surfacing) && (
            <div className="absolute top-12 right-3 z-10 flex max-h-[calc(100%-11rem)] w-64 flex-col gap-2">
              {rigging && rig && (
                <RigPanel
                  rig={rig}
                  pose={posing}
                  onPose={(next) => scene && setPosed({ scene, pose: next })}
                />
              )}
              {surfacing && (
                <SurfacePanel
                  palette={palette}
                  detail={detail}
                  layers={layers}
                  onLayers={setLayers}
                  look={colorLook}
                  onLook={(next) => {
                    if (palette) {
                      setLooked({ palette, look: next });
                    }
                  }}
                  flat={flat}
                  onFlat={setFlat}
                  pointed={pointed}
                  onSend={(text) => onCompose(text, [], "color")}
                />
              )}
            </div>
          )}
        </>
      )}
      {model && !in3d && (
        <div className="absolute inset-0 z-10 bg-canvas">
          {mode === "renders" ? (
            <Renders model={model} />
          ) : (
            <Checks model={model} />
          )}
          {compact && (
            <button
              type="button"
              onClick={() => onMode("3d")}
              className={cn(
                "absolute right-3 flex h-7 items-center gap-1.5 rounded-md border border-line-control bg-panel px-2.5 text-label hover:bg-hover",
                // Under the checks' own button, which sits where this does over the renders.
                mode === "renders" ? "top-3" : "bottom-3",
              )}
            >
              <Icon name="model" />
              Back to 3D
            </button>
          )}
        </div>
      )}
      {showing && failure && (
        <Notice
          title={`Couldn't load the new ${GLB}.`}
          className="absolute right-24 bottom-3 left-3 z-20"
        >
          Showing the version from {timeOfDay(shown.built)}. Ask the agent to
          rebuild it. {failure}
        </Notice>
      )}
    </section>
  );
}
