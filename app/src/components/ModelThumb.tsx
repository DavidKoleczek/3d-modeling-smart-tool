import { useEffect, useState } from "react";

import { Icon } from "@/components/ui/icon";
import { firstRender, readModelFile, type ModelSummary } from "@/lib/api";
import { pastelFor } from "@/lib/models";
import { cn } from "@/lib/utils";

const SIZES = {
  20: "size-5 rounded-sm",
  32: "size-8 rounded-md",
  40: "size-10 rounded-md",
  fill: "size-full rounded-sm",
};
const ICONS = { 20: null, 32: 16, 40: 20, fill: 24 } as const;

/** A model's first render, read again each time it is rebuilt, or a pastel tile until it has one. */
export function ModelThumb({
  model,
  size = 40,
}: {
  model: ModelSummary;
  size?: keyof typeof SIZES;
}) {
  const render = firstRender(model);
  const [source, setSource] = useState<string | null>(null);
  // Read again on a rebuild, showing the last render until the new one arrives.
  const built = model.built;

  useEffect(() => {
    if (!render) {
      return;
    }
    let current = true;
    readModelFile(model.name, render).then(
      (file) => {
        if (current) {
          setSource(`data:${file.mimeType};base64,${file.base64}`);
        }
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [model.name, render, built]);

  const url = render ? source : null;
  return url ? (
    <img
      src={url}
      alt=""
      className={cn(
        "block shrink-0 border border-line object-cover",
        SIZES[size],
      )}
    />
  ) : (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center text-on-pastel",
        SIZES[size],
        pastelFor(model.name),
      )}
    >
      {ICONS[size] && <Icon name="model" size={ICONS[size]} />}
    </span>
  );
}
