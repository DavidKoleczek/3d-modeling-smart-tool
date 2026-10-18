import { useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useModelImage } from "@/lib/images";

/** One of a model's images to see large, at `path` relative to the model, as of `version` of it. */
export type ShownImage = { path: string; version?: string | null };

function name(path: string) {
  return path.replace(/^(references|renders)\//, "");
}

/** `image` of model `model` large, with its name and size, until the person closes it. */
export function ImageDialog({
  model,
  image,
  onClose,
}: {
  model: string;
  image: ShownImage | null;
  onClose: () => void;
}) {
  const { url, error } = useModelImage(
    model,
    image?.path ?? null,
    image?.version,
  );
  const [size, setSize] = useState<{ url: string; text: string } | null>(null);

  return (
    <Dialog open={image !== null} onOpenChange={(open) => !open && onClose()}>
      {image && (
        <DialogContent
          title={name(image.path)}
          subtitle={url && size?.url === url ? size.text : undefined}
          className="sm:max-w-[min(90vw,960px)]"
        >
          <div className="grid min-h-40 flex-1 place-items-center bg-canvas p-4">
            {url ? (
              <img
                src={url}
                alt={name(image.path)}
                onLoad={(event) =>
                  setSize({
                    url,
                    text: `${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`,
                  })
                }
                className="mx-auto block max-h-[calc(100dvh-160px)] w-full object-contain"
              />
            ) : (
              <p className="text-ink-muted">
                {error ? `Couldn't read ${image.path}. ${error}` : "Reading..."}
              </p>
            )}
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
