import {
  Mesh,
  SkinnedMesh,
  Texture,
  type Material,
  type Object3D,
} from "three";
import {
  GLTFLoader,
  type GLTFParser,
} from "three/examples/jsm/loaders/GLTFLoader.js";

/**
 * Decode images embedded in the GLB straight from their bytes. GLTFLoader would fetch them from `blob:` URLs, which
 * the view's CSP refuses, leaving the model untextured.
 */
function embeddedImages(parser: GLTFParser) {
  const loadImageSource = parser.loadImageSource;
  parser.loadImageSource = async (sourceIndex, imageLoader) => {
    const source = parser.json.images[sourceIndex];
    if (source.bufferView === undefined) {
      return loadImageSource.call(parser, sourceIndex, imageLoader);
    }
    const view: ArrayBuffer = await parser.getDependency(
      "bufferView",
      source.bufferView,
    );
    const bitmap = await createImageBitmap(
      new Blob([view], { type: source.mimeType }),
      { premultiplyAlpha: "none" },
    );
    const texture = new Texture(bitmap);
    texture.needsUpdate = true;
    texture.userData.mimeType = source.mimeType;
    return texture;
  };
  return { name: "modeling-3d-embedded-images" };
}

const loader = new GLTFLoader().register(embeddedImages);

function bytesOf(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

/** The scene in a GLB, from its bytes: the view's CSP refuses fetches, even of `blob:` URLs, so nothing is loaded. */
export async function parseGlb(base64: string): Promise<Object3D> {
  return (await loader.parseAsync(bytesOf(base64), "")).scene;
}

/** Free what `scene` holds on the GPU, since each rebuild of a model replaces the whole scene. */
export function dispose(scene: Object3D): void {
  scene.traverse((object) => {
    if (!(object instanceof Mesh)) {
      return;
    }
    object.geometry.dispose();
    // A skeleton keeps its bones' matrices in a texture on the GPU. Skins that share one free it once.
    if (object instanceof SkinnedMesh) {
      object.skeleton.dispose();
    }
    const materials: Material[] = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value && (value as Texture).isTexture) {
          (value as Texture).dispose();
        }
      }
      material.dispose();
    }
  });
}
