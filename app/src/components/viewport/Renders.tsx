import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { rendersOf, type ModelSummary } from "@/lib/api";
import { useModelImage } from "@/lib/images";
import { useShortcuts } from "@/lib/shortcuts";
import { timeOfDay } from "@/lib/time";
import { cn } from "@/lib/utils";

function name(path: string) {
  return path.replace(/^renders\//, "");
}

/** One render in the strip along the top, which brings it up below. */
function Thumb({
  model,
  path,
  selected,
  onSelect,
}: {
  model: ModelSummary;
  path: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const { url } = useModelImage(model.name, path, model.built);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (selected) {
      button.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [selected]);

  return (
    <li className="shrink-0">
      <button
        ref={button}
        type="button"
        onClick={onSelect}
        aria-label={name(path)}
        aria-current={selected || undefined}
        title={name(path)}
        className={cn(
          "block size-18 overflow-hidden rounded-md border bg-panel p-0.5",
          selected
            ? "border-accent ring-1 ring-accent"
            : "border-line hover:border-line-control",
        )}
      >
        {url ? (
          <img
            src={url}
            alt=""
            className="size-full rounded-sm bg-canvas object-contain"
          />
        ) : (
          <span className="block size-full rounded-sm bg-field" />
        )}
      </button>
    </li>
  );
}

/** The render picked in the strip, as large as the room below it allows, with its name and size. */
function Stage({
  model,
  path,
  place,
}: {
  model: ModelSummary;
  path: string;
  place: string;
}) {
  const { url, error } = useModelImage(model.name, path, model.built);
  const [size, setSize] = useState<{ url: string; text: string } | null>(null);

  return (
    <figure className="flex min-h-0 flex-1 flex-col gap-2 px-4 pb-3">
      <div className="relative grid min-h-0 flex-1 place-items-center">
        {url ? (
          <img
            src={url}
            alt={name(path)}
            onLoad={(event) =>
              setSize({
                url,
                text: `${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`,
              })
            }
            className="absolute inset-0 size-full object-contain"
          />
        ) : (
          <p className="text-ink-muted">
            {error ? `Couldn't read ${name(path)}. ${error}` : "Reading..."}
          </p>
        )}
      </div>
      <figcaption className="flex shrink-0 justify-center gap-3 mono-annotation">
        <span className="text-ink">{name(path)}</span>
        {size?.url === url && (
          <span className="text-ink-muted">{size.text}</span>
        )}
        <span className="text-ink-muted">{place}</span>
      </figcaption>
    </figure>
  );
}

/**
 * What the agent rendered and looked at, as of the last build: a strip of them along the top, and the one picked in it
 * large below. Left and Right step through them.
 */
export function Renders({ model }: { model: ModelSummary }) {
  const renders = rendersOf(model);
  const [picked, setPicked] = useState<{ model: string; path: string } | null>(
    null,
  );
  const strip = useRef<HTMLOListElement>(null);
  const [ends, setEnds] = useState({ start: true, end: true });
  // The one picked, while this model still has it; the first otherwise, as when another model comes into view.
  const index = Math.max(
    0,
    picked?.model === model.name ? renders.indexOf(picked.path) : 0,
  );
  const current = renders[index];

  const select = (at: number) => {
    const path = renders[(at + renders.length) % renders.length];
    if (path) {
      setPicked({ model: model.name, path });
    }
  };

  useShortcuts({
    arrowleft: () => select(index - 1),
    arrowright: () => select(index + 1),
  });

  // Which ends of the strip are in view, so the arrows toward them go.
  const measure = useCallback(() => {
    const element = strip.current;
    if (element) {
      setEnds({
        start: element.scrollLeft <= 1,
        end:
          element.scrollLeft + element.clientWidth >= element.scrollWidth - 1,
      });
    }
  }, []);

  useEffect(() => {
    measure();
    const element = strip.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure, renders.length]);

  // Arrows only while some renders are out of view; the one toward an end in view hides but keeps its room, so the
  // strip holds still.
  const scrolls = !(ends.start && ends.end);
  const scroll = (direction: -1 | 1) =>
    strip.current?.scrollBy({
      left: direction * strip.current.clientWidth * 0.8,
      behavior: "smooth",
    });

  return (
    <div className="@container absolute inset-0 flex flex-col">
      <div className="flex h-13 shrink-0 items-center px-3">
        <div className="flex h-7 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5">
          <Icon name="image" />
          <span className="mono-annotation text-ink">
            {renders.length} {renders.length === 1 ? "render" : "renders"}
          </span>
          {model.built && (
            <span className="hidden mono-annotation text-ink-muted @min-[560px]:inline">
              from the build at {timeOfDay(model.built, true)}
            </span>
          )}
        </div>
      </div>
      {current === undefined ? (
        <p className="mt-8 text-center text-ink-muted">
          The agent hasn't rendered {model.name} yet.
        </p>
      ) : (
        <>
          <div className="flex shrink-0 items-center gap-1 px-2 pb-3">
            {scrolls && (
              <Button
                size="lg"
                icon
                aria-label="Earlier renders"
                disabled={ends.start}
                onClick={() => scroll(-1)}
                className={cn(ends.start && "invisible")}
              >
                <Icon name="chevron" size={20} className="rotate-90" />
              </Button>
            )}
            <ol
              ref={strip}
              aria-label="Renders"
              onScroll={measure}
              className="flex min-w-0 flex-1 scrollbar-none justify-center-safe gap-2 overflow-x-auto p-0.5"
            >
              {renders.map((path, at) => (
                <Thumb
                  key={path}
                  model={model}
                  path={path}
                  selected={at === index}
                  onSelect={() => select(at)}
                />
              ))}
            </ol>
            {scrolls && (
              <Button
                size="lg"
                icon
                aria-label="Later renders"
                disabled={ends.end}
                onClick={() => scroll(1)}
                className={cn(ends.end && "invisible")}
              >
                <Icon name="chevron" size={20} className="-rotate-90" />
              </Button>
            )}
          </div>
          <Stage
            key={current}
            model={model}
            path={current}
            place={`${index + 1} of ${renders.length}`}
          />
        </>
      )}
    </div>
  );
}
