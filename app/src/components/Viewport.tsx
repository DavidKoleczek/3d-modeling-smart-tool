import { Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Box, LoaderCircle } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Box3,
  PerspectiveCamera,
  PMREMGenerator,
  Sphere,
  Vector3,
  type Object3D,
} from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import { StatusBadge } from "@/components/StatusBadge";
import {
  GLB,
  readModelFile,
  type ModelListing,
  type ModelSummary,
} from "@/lib/api";
import { describe } from "@/lib/errors";
import { dispose, parseGlb } from "@/lib/scene";

type Shown = { name: string; scene: Object3D };

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

/**
 * Frames the model when it is first shown, and again on each rebuild unless the person has moved the camera since,
 * or the rebuilt model would swallow the camera.
 */
function Framing({ scene }: { scene: Object3D }) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as Orbit | null;
  const moved = useRef(false);

  useEffect(() => {
    if (!controls) {
      return;
    }
    const onStart = () => {
      moved.current = true;
    };
    controls.addEventListener("start", onStart);
    return () => controls.removeEventListener("start", onStart);
  }, [controls]);

  useLayoutEffect(() => {
    const sphere = new Box3()
      .setFromObject(scene)
      .getBoundingSphere(new Sphere());
    const inside =
      camera.position.distanceTo(sphere.center) < sphere.radius * MARGIN;
    if ((moved.current && !inside) || !(camera instanceof PerspectiveCamera)) {
      return;
    }
    // Whichever field of view is narrower decides, so the model fits a tall viewport as well as a wide one.
    const vertical = (camera.fov * Math.PI) / 180;
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
    const distance =
      (sphere.radius * MARGIN) / Math.sin(Math.min(vertical, horizontal) / 2);
    camera.position
      .copy(sphere.center)
      .addScaledVector(VIEW_DIRECTION, distance);
    camera.lookAt(sphere.center);
    controls?.target.copy(sphere.center);
    controls?.update();
    moved.current = false;
  }, [scene, camera, controls]);

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

function Message({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="relative m-auto flex max-w-xs flex-col items-center gap-3 p-4 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl border bg-background shadow-sm">
        {icon}
      </div>
      <p className="text-sm font-medium">{title}</p>
      {children && (
        <p className="text-sm wrap-break-word text-muted-foreground">
          {children}
        </p>
      )}
    </div>
  );
}

/** The model in view, in 3D, reloaded each time its GLB is rebuilt. */
export function Viewport({
  listing,
  model,
}: {
  listing: ModelListing | null;
  model: ModelSummary | null;
}) {
  const [shown, setShown] = useState<Shown | null>(null);
  const [error, setError] = useState<{ name: string; text: string } | null>(
    null,
  );
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
            setShown({ name, scene });
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
  useEffect(
    () => () => {
      if (scene) {
        dispose(scene);
      }
    },
    [scene],
  );

  const showing = shown !== null && shown.name === name;
  const failure = error !== null && error.name === name ? error.text : null;

  let message: ReactNode = null;
  if (listing === null) {
    message = (
      <Message
        icon={<LoaderCircle className="size-6 animate-spin text-primary" />}
        title="Looking for models"
      />
    );
  } else if (model === null) {
    message = (
      <Message
        icon={<Box className="size-6 text-primary" />}
        title="No models yet"
      >
        Start one with New model, or ask your agent to, and it appears here as
        it is built.
      </Message>
    );
  } else if (!model.built) {
    message =
      model.status === "running" ? (
        <Message
          icon={<LoaderCircle className="size-6 animate-spin text-primary" />}
          title={`Building ${model.name}`}
        >
          It appears here once the first version is built.
        </Message>
      ) : (
        <Message
          icon={<Box className="size-6 text-primary" />}
          title={`${model.name} has no ${GLB}`}
        >
          Ask your agent to change it, and it will appear here once it is built.
        </Message>
      );
  } else if (!showing) {
    message = failure ? (
      <Message
        icon={<Box className="size-6 text-destructive" />}
        title={`Could not show ${model.name}`}
      >
        {failure}
      </Message>
    ) : (
      <Message
        icon={<LoaderCircle className="size-6 animate-spin text-primary" />}
        title={`Loading ${model.name}`}
      />
    );
  }

  return (
    <section className="relative flex min-h-48 flex-1 overflow-hidden rounded-xl border bg-muted/40">
      {message ?? (
        <div className="absolute inset-0">
          <Canvas
            camera={{ position: [2, 1.5, 2.5], fov: 45, near: 0.01, far: 1000 }}
            dpr={[1, 2]}
          >
            <RoomLighting />
            <directionalLight position={[3, 6, 4]} intensity={1.5} />
            {/* Keyed by model, so switching models frames the new one however the camera was left. */}
            <group key={shown!.name}>
              <primitive object={shown!.scene} />
              <Framing scene={shown!.scene} />
            </group>
            <Grid
              infiniteGrid
              cellSize={0.1}
              sectionSize={1}
              fadeDistance={25}
              cellColor="#a1a1aa"
              sectionColor="#71717a"
            />
            <OrbitControls makeDefault />
          </Canvas>
        </div>
      )}
      {model && (
        <div className="pointer-events-none absolute top-3 left-3 flex items-center gap-2 rounded-lg border bg-background/90 px-2 py-1 shadow-sm">
          <span className="text-sm font-medium">{model.name}</span>
          <StatusBadge status={model.status} />
        </div>
      )}
      {showing && failure && (
        <p className="absolute inset-x-3 bottom-3 rounded-lg border border-destructive/30 bg-background/90 px-2 py-1 text-xs text-destructive">
          Showing the last version that loaded. {failure}
        </p>
      )}
    </section>
  );
}
