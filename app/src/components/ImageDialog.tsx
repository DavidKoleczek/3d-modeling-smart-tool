import { useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useModelImage } from "@/lib/images";

/** One of a model's images to see large, at `path` relative to the model, as of `version` of it. */
export type ShownImage = { path: string; version?: string | null };

/** An image the page holds already, such as one added to a message, by its name and a URL of its own. */
export type HeldImage = { name: string; url: string };

function name(path: string) {
  return path.replace(/^(references|renders|checks)\//, "");
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
  return (
    <LargeImage
      title={image && name(image.path)}
      url={url}
      missing={
        image &&
        (error ? `Couldn't read ${image.path}. ${error}` : "Reading...")
      }
      onClose={onClose}
    />
  );
}

/** `image`, which the page holds already, large, with its name and size, until the person closes it. */
export function HeldImageDialog({
  image,
  onClose,
}: {
  image: HeldImage | null;
  onClose: () => void;
}) {
  return (
    <LargeImage
      title={image?.name ?? null}
      url={image?.url ?? null}
      missing={null}
      onClose={onClose}
    />
  );
}

/** The image at `url` large, open while it has a `title`; `missing` says why there is no `url` yet. */
function LargeImage({
  title,
  url,
  missing,
  onClose,
}: {
  title: string | null;
  url: string | null;
  missing: string | null;
  onClose: () => void;
}) {
  const [size, setSize] = useState<{ url: string; text: string } | null>(null);

  return (
    <Dialog open={title !== null} onOpenChange={(open) => !open && onClose()}>
      {title !== null && (
        <DialogContent
          title={title}
          subtitle={url && size?.url === url ? size.text : undefined}
          className="sm:max-w-[min(90vw,960px)]"
        >
          <div className="grid min-h-40 flex-1 place-items-center bg-canvas p-4">
            {url ? (
              <img
                src={url}
                alt={title}
                onLoad={(event) =>
                  setSize({
                    url,
                    text: `${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`,
                  })
                }
                className="mx-auto block max-h-[calc(100dvh-160px)] w-full object-contain"
              />
            ) : (
              <p className="text-ink-muted">{missing}</p>
            )}
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
