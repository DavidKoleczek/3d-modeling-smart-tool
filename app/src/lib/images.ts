import { useEffect, useState } from "react";

import { readModelFile } from "@/lib/api";
import { describe } from "@/lib/errors";

// Enough for every render of a few models, so going back and forth between them reads each once.
const CACHED = 48;

const cache = new Map<string, Promise<string>>();

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
