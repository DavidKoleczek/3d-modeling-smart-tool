import { useEffect, useState } from "react";

import { readModelFile } from "@/lib/api";
import { describe } from "@/lib/errors";

// Enough for every render of a few models, so going back and forth between them reads each once.
const CACHED = 48;

// Twice the largest a thumbnail shows, for screens of twice the pixel density.
const THUMBNAIL = 256;

const cache = new Map<string, Promise<string>>();

/**
 * The image at the data URL `url` at most `THUMBNAIL` pixels on its shorter side, for a thumbnail: a grid of full size
 * images scales each of them again on every frame it scrolls, and keeps all of them decoded.
 */
export async function shrinkImage(url: string): Promise<string> {
  const image = new Image();
  image.src = url;
  await image.decode();
  const scale = THUMBNAIL / Math.min(image.naturalWidth, image.naturalHeight);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (scale >= 1 || !context) {
    return url;
  }
  canvas.width = Math.round(image.naturalWidth * scale);
  canvas.height = Math.round(image.naturalHeight * scale);
  context.imageSmoothingQuality = "high";
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/webp");
}

/** A model's image as a data URL, read once for each `version` of it, such as the build it came from. */
function readImage(
  model: string,
  path: string,
  version: string,
): Promise<string> {
  const key = JSON.stringify([model, path, version]);
  let image = cache.get(key);
  if (!image) {
    image = readModelFile(model, path).then(
      (file) => `data:${file.mimeType};base64,${file.base64}`,
    );
    // A failed read is tried again next time.
    image.catch(() => cache.delete(key));
    cache.set(key, image);
    for (const old of cache.keys()) {
      if (cache.size <= CACHED) {
        break;
      }
      cache.delete(old);
    }
  }
  return image;
}

/** The image at `path` in model `model`, read through the host: its data URL once read, or why it could not be. */
export function useModelImage(
  model: string,
  path: string | null,
  version: string | null = null,
): { url: string | null; error: string | null } {
  const [loaded, setLoaded] = useState<{
    key: string;
    url: string | null;
    error: string | null;
  } | null>(null);
  const key = JSON.stringify([model, path, version]);

  useEffect(() => {
    if (path === null) {
      return;
    }
    let current = true;
    readImage(model, path, version ?? "").then(
      (url) => current && setLoaded({ key, url, error: null }),
      (cause: unknown) =>
        current && setLoaded({ key, url: null, error: describe(cause) }),
    );
    return () => {
      current = false;
    };
  }, [model, path, version, key]);

  return loaded?.key === key
    ? { url: loaded.url, error: loaded.error }
    : { url: null, error: null };
}
