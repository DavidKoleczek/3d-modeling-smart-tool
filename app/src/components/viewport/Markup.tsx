import { useThree } from "@react-three/fiber";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
  type SyntheticEvent,
} from "react";
import type { Object3D } from "three";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Notice } from "@/components/ui/notice";
import { Tooltip } from "@/components/ui/tooltip";
import type { ModelSummary } from "@/lib/api";
import { describe } from "@/lib/errors";
import {
  CORNERS,
  NO_MARKUP,
  boxBetween,
  described,
  marked,
  markupFiles,
  markupPrompt,
  markupRequest,
  moveBox,
  nextId,
  oppositeCorner,
  pointIn,
  type Box,
  type Corner,
  type Mark,
  type Markup as MarkupDraft,
  type Point,
  type Snapshot,
  type Still,
} from "@/lib/markup";
import { useShortcuts } from "@/lib/shortcuts";
import { cn, submitsOnEnter } from "@/lib/utils";

export type CaptureApi = { capture: () => Still | null };

/** What a drag is doing, from where it started. */
type Gesture =
  | { kind: "draw"; from: Point }
  | { kind: "move"; id: number; from: Point; box: Box }
  | { kind: "resize"; id: number; anchor: Point };

// A drag shorter than this either way, in CSS pixels, is a click rather than a box.
const SMALLEST = 8;
const NOTE_WIDTH = 256;
// About what a note takes with two lines written, to decide which side of its box it fits.
const NOTE_HEIGHT = 112;
const GAP = 8;
// What the bar along the bottom covers once it holds the message, which a note below its box stays clear of.
const BAR = 96;
const LABEL = 24;

const HANDLES: Record<Corner, string> = {
  "top-left": "-top-1.5 -left-1.5 cursor-nwse-resize",
  "top-right": "-top-1.5 -right-1.5 cursor-nesw-resize",
  "bottom-left": "-bottom-1.5 -left-1.5 cursor-nesw-resize",
  "bottom-right": "-right-1.5 -bottom-1.5 cursor-nwse-resize",
};

/**
 * Inside the canvas: gives `capture`, which renders the view once more and keeps it as a still, leaving out what has
 * `userData.inStills` false, like the dimension lines.
 */
export function CaptureDriver({
  apiRef,
}: {
  apiRef: RefObject<CaptureApi | null>;
}) {
  const gl = useThree((state) => state.gl);
  const scene = useThree((state) => state.scene);
  const camera = useThree((state) => state.camera);

  useEffect(() => {
    apiRef.current = {
      capture: () => {
        const source = gl.domElement;
        const still = document.createElement("canvas");
        still.width = source.width;
        still.height = source.height;
        const context = still.getContext("2d");
        if (!context) {
          return null;
        }
        // The scene renders onto a transparent canvas, which the agent would otherwise see as black or checkered.
        context.fillStyle = getComputedStyle(source)
          .getPropertyValue("--canvas")
          .trim();
        context.fillRect(0, 0, still.width, still.height);
        const hidden: Object3D[] = [];
        scene.traverse((object) => {
          if (object.visible && object.userData.inStills === false) {
            object.visible = false;
            hidden.push(object);
          }
        });
        // Rendered again here, since the canvas keeps no frame once it is on screen.
        gl.render(scene, camera);
        context.drawImage(source, 0, 0);
        for (const object of hidden) {
          object.visible = true;
        }
        return {
          url: still.toDataURL("image/png"),
          width: still.width,
          height: still.height,
          scale: gl.getPixelRatio(),
        };
      },
    };
  }, [apiRef, gl, scene, camera]);

  return null;
}

/** Where a mark's note goes: below its box, else above, beside, or over its bottom, inside the still. */
function notePlace(box: Box, width: number, height: number): CSSProperties {
  const left = Math.max(GAP, Math.min(box.x * width, width - NOTE_WIDTH - GAP));
  const top = box.y * height;
  const bottom = (box.y + box.height) * height;
  if (height - bottom - GAP - BAR >= NOTE_HEIGHT) {
    return { left, top: bottom + GAP };
  }
  if (top - GAP >= NOTE_HEIGHT) {
    return { left, bottom: height - top + GAP };
  }
  const y = Math.max(GAP, Math.min(top, height - NOTE_HEIGHT - BAR));
  const right = (box.x + box.width) * width;
  if (width - right - GAP >= NOTE_WIDTH) {
    return { left: right + GAP, top: y };
  }
  if (box.x * width - GAP >= NOTE_WIDTH) {
    return { left: box.x * width - GAP - NOTE_WIDTH, top: y };
  }
  return { left, bottom: Math.max(GAP, height - bottom + GAP) };
}

function placed(box: Box): CSSProperties {
  return {
    left: `${box.x * 100}%`,
    top: `${box.y * 100}%`,
    width: `${box.width * 100}%`,
    height: `${box.height * 100}%`,
  };
}

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Keeps a press on the note to the note, so it neither starts a box nor moves focus off the still's marks. */
function keep(event: SyntheticEvent) {
  event.stopPropagation();
}

/** The open mark's note, where the person writes what to change inside its box. */
function Note({
  mark,
  place,
  onChange,
  onDone,
  onDelete,
}: {
  mark: Mark;
  place: CSSProperties;
  onChange: (note: string) => void;
  onDone: () => void;
  onDelete: () => void;
}) {
  // A mark opened with nothing written is still being made, and goes on its own when closed empty, so it offers no Del.
  const [made] = useState(() => mark.note.trim() !== "");
  return (
    <div
      style={{ ...place, width: NOTE_WIDTH }}
      onPointerDown={keep}
      onMouseDown={keep}
      className="absolute z-20 cursor-auto rounded-lg bg-raised p-1.5 shadow-popover"
    >
      <textarea
        autoFocus
        value={mark.note}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onDone();
          } else {
            submitsOnEnter(onDone)(event);
          }
        }}
        rows={2}
        placeholder="What should change here?"
        aria-label="What to change here"
        className="block field-sizing-content max-h-32 min-h-10 w-full resize-none rounded-sm bg-transparent py-1 pr-7 pl-1.5 text-ink outline-none placeholder:text-ink-muted focus-visible:outline-none"
      />
      {/* Closes like Esc or a click elsewhere: what is written stays, and a mark with nothing written goes. */}
      <Button
        size="sm"
        icon
        aria-label="Close"
        title="Close"
        onClick={onDone}
        className="absolute top-1.5 right-1.5"
      >
        <Icon name="close" />
      </Button>
      <div className="mt-1 flex items-center gap-1.5">
        {made && (
          <Button size="sm" title="Delete this mark" onClick={onDelete}>
            Del
          </Button>
        )}
        {/* Saving an empty note would drop its mark, which Del is for. */}
        <Button
          className="ml-auto"
          variant="primary"
          size="sm"
          disabled={!mark.note.trim()}
          onClick={onDone}
        >
          Save
        </Button>
      </div>
    </div>
  );
}

/** One box over the still, with its note above it, or handles to resize it while open. */
function MarkBox({
  mark,
  open,
  width,
  height,
  onPress,
  onResize,
}: {
  mark: Mark;
  open: boolean;
  width: number;
  height: number;
  onPress: (event: PointerEvent<HTMLDivElement>) => void;
  onResize: (event: PointerEvent<HTMLSpanElement>, corner: Corner) => void;
}) {
  const roomAbove = mark.y * height >= LABEL;
  // Toward the right edge, the label runs back over the box instead of off the still.
  const fromRight = mark.x * width > width - 220;
  return (
    <div
      onPointerDown={onPress}
      style={placed(mark)}
      className={cn(
        "absolute border-2 border-accent-ink",
        open
          ? "z-10 cursor-move bg-accent-ink/15"
          : "cursor-pointer bg-accent-ink/8 hover:bg-accent-ink/15",
      )}
    >
      {!open && mark.note.trim() && (
        <span
          className={cn(
            "absolute max-w-56 truncate rounded-sm bg-panel px-1.5 py-0.5 text-caption text-ink shadow-popover",
            roomAbove ? "bottom-full mb-1" : "top-1",
            fromRight
              ? roomAbove
                ? "-right-0.5"
                : "right-1"
              : roomAbove
                ? "-left-0.5"
                : "left-1",
          )}
        >
          {mark.note.trim()}
        </span>
      )}
      {open &&
        CORNERS.map((corner) => (
          <span
            key={corner}
            onPointerDown={(event) => onResize(event, corner)}
            className={cn(
              "absolute size-2.5 border-[1.5px] border-accent-ink bg-panel",
              HANDLES[corner],
            )}
          />
        ))}
    </div>
  );
}

/** The box being dragged out. */
function Drawing({ box }: { box: Box }) {
  return (
    <div
      style={placed(box)}
      className="pointer-events-none absolute z-10 border-2 border-dashed border-accent-ink bg-accent-ink/8"
    />
  );
}

/** The marked views down the side, in the order they go to the agent, each opening to mark it further. */
function Views({
  snapshots,
  viewing,
  onShow,
  onRemove,
}: {
  snapshots: Snapshot[];
  viewing: number | null;
  onShow: (id: number) => void;
  onRemove: (id: number) => void;
}) {
  return (
    <ol
      aria-label="Marked views"
      className="absolute top-14 left-3 z-20 flex max-h-[calc(100%-9.5rem)] flex-col gap-1.5 overflow-y-auto rounded-md border border-line bg-panel p-1"
    >
      {snapshots.map((snapshot, index) => {
        const current = snapshot.id === viewing;
        const marks = described(snapshot.marks).length;
        const label = `View ${index + 1}, ${counted(marks, "mark", "marks")}`;
        return (
          <li key={snapshot.id} className="group relative shrink-0">
            <Tooltip content={label} side="right">
              <button
                type="button"
                onClick={() => onShow(snapshot.id)}
                aria-label={label}
                aria-current={current || undefined}
                className={cn(
                  "relative block h-12 w-16 overflow-hidden rounded-sm border bg-canvas",
                  current
                    ? "border-accent ring-1 ring-accent"
                    : "border-line hover:border-line-control",
                )}
              >
                <img
                  src={snapshot.still.url}
                  alt=""
                  draggable={false}
                  className="size-full object-cover"
                />
                {marks > 0 && (
                  <span className="absolute bottom-0.5 left-0.5 grid h-4 min-w-4 place-items-center rounded-sm bg-accent-ink px-0.5 mono-annotation text-panel">
                    {marks}
                  </span>
                )}
              </button>
            </Tooltip>
            <button
              type="button"
              onClick={() => onRemove(snapshot.id)}
              aria-label={`Delete view ${index + 1}`}
              title="Delete this view and its marks"
              className={cn(
                "absolute -top-1 -right-1 size-5 place-items-center rounded-sm border border-line bg-panel text-ink-muted shadow-popover hover:text-ink",
                current
                  ? "grid"
                  : "hidden group-focus-within:grid group-hover:grid",
              )}
            >
              <Icon name="close" />
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Mark up, in its own group beside the viewport's tools, which switches a drag between drawing boxes and turning the
 * model.
 */
function MarkToggle({
  marking,
  compact,
  onToggle,
}: {
  marking: boolean;
  compact: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-center rounded-md border border-line bg-panel p-0.75">
      <Tooltip
        content={
          marking
            ? "Back to turning the model"
            : "Drag over the model to mark what to change"
        }
      >
        <Button
          size={compact ? "sm" : "md"}
          aria-label="Mark up"
          aria-pressed={marking}
          onClick={onToggle}
          className="pr-1"
        >
          <Icon name="mark" size={compact ? 16 : 20} />
          {!compact && "Mark up"}
          <Kbd>M</Kbd>
        </Button>
      </Tooltip>
    </div>
  );
}

/**
 * Along the bottom: how to mark while Mark up is on; once something is marked, a message to go with the marks, and
 * Add to message, which puts them in the composer beside Activity. The message goes after the views, so it can speak
 * to all of them.
 */
function Bar({
  marking,
  marks,
  views,
  viewed,
  running,
  composing,
  model,
  message,
  onMessage,
  onDiscard,
  onCompose,
}: {
  marking: boolean;
  marks: number;
  views: number;
  /** Whether a snapshot is in view, which more boxes go on, rather than the live view. */
  viewed: boolean;
  running: boolean;
  composing: boolean;
  model: string;
  message: string;
  onMessage: (message: string) => void;
  onDiscard: () => void;
  onCompose: () => void;
}) {
  if (marks === 0) {
    return (
      marking && (
        <p className="flex h-7 max-w-full items-center gap-2 rounded-md border border-line bg-panel px-2.5 text-label shadow-popover">
          <Icon name="mark" className="shrink-0 text-accent-ink" />
          <span className="truncate">
            {viewed ? "Drag to mark more here" : "Drag to mark what to change"}
          </span>
        </p>
      )
    );
  }
  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onCompose();
      }}
      aria-label="Add the marks to the message"
      className="pointer-events-auto w-full max-w-120 rounded-lg border border-line bg-panel p-1.5 shadow-popover"
    >
      <textarea
        value={message}
        onChange={(event) => onMessage(event.target.value)}
        onKeyDown={submitsOnEnter(onCompose)}
        rows={1}
        placeholder="Anything else to tell the agent?"
        aria-label="Anything else to tell the agent"
        className="block field-sizing-content max-h-24 min-h-8 w-full resize-none rounded-md border border-line-control bg-field px-2 py-1.5 text-ink transition-colors outline-none placeholder:text-ink-muted focus-visible:border-ink focus-visible:bg-panel focus-visible:outline-none"
      />
      <div className="mt-1.5 flex items-center gap-1.5 pl-1">
        <Icon name="mark" className="shrink-0 text-accent-ink" />
        <span className="min-w-0 flex-1 truncate mono-annotation text-ink">
          {counted(marks, "mark", "marks")}
          {views > 1 && ` on ${views} views`}
        </span>
        <Button
          variant="secondary"
          size="sm"
          onClick={onDiscard}
          title="Clear every view, mark, and the message"
        >
          Discard
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={composing}
          title={
            running
              ? `Put the marked views in the message to the agent working on ${model}, to steer it from there`
              : `Put the marked views in the message asking for a change to ${model}, to pick the AI model and send from there`
          }
        >
          {composing ? <LoadingMark /> : <Icon name="sidebar-right" />}
          Add to message
        </Button>
      </div>
    </form>
  );
}

/**
 * The 3D view, `children`, to mark up as well as look at. With Mark up on, dragging over the live view draws a box and
 * holds that view still as a snapshot down the side, where more boxes can go on it; turning it off goes back to the
 * live view to turn the model, and on again marks it from there. Each box takes a note on what to change in it, moves
 * by dragging, and resizes by its corners while open. Add to message puts the views in the composer in order, with
 * their notes, then the message.
 */
export function Markup({
  model,
  onCompose,
  active,
  tools,
  compact,
  markup,
  onChange,
  capture,
  children,
}: {
  /** The model in view, whose agent the marks are for. */
  model: ModelSummary;
  /** Put the marked views and their notes in the message to the model's agent, to send from there. */
  onCompose: (text: string, files: File[]) => void;
  /** Whether the 3D view is in front, rather than the renders. */
  active: boolean;
  /** The viewport's own tools, which Mark up goes beside. */
  tools: ReactNode;
  compact: boolean;
  markup: MarkupDraft;
  onChange: (change: (markup: MarkupDraft) => MarkupDraft) => void;
  capture: RefObject<CaptureApi | null>;
  children: ReactNode;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const [room, setRoom] = useState({ width: 0, height: 0 });
  const [open, setOpen] = useState<number | null>(null);
  const [drawing, setDrawing] = useState<Box | null>(null);
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { snapshots, marking } = markup;
  const viewed =
    snapshots.find((snapshot) => snapshot.id === markup.viewing) ?? null;
  const ready = marked(snapshots);
  const count = ready.reduce((sum, snapshot) => sum + snapshot.marks.length, 0);

  useEffect(() => {
    const element = surface.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(() =>
      setRoom({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // The still as large as the viewport allows, at its own shape, so the marks stay on what they cover as panes move.
  const ratio = viewed ? viewed.still.width / viewed.still.height : 1;
  const width = Math.min(room.width, room.height * ratio);
  const height = width / ratio;

  const changeMarks = (id: number, change: (marks: Mark[]) => Mark[]) =>
    onChange((current) => ({
      ...current,
      snapshots: current.snapshots.map((snapshot) =>
        snapshot.id === id
          ? { ...snapshot, marks: change(snapshot.marks) }
          : snapshot,
      ),
    }));

  // Closes the open note, dropping its mark if nothing was written in it.
  const close = () => {
    setOpen(null);
    onChange((current) => ({
      ...current,
      snapshots: current.snapshots.map((snapshot) => ({
        ...snapshot,
        marks: described(snapshot.marks),
      })),
    }));
  };

  // Shows snapshot `id` to mark, or the live view for null, letting go of any other snapshot left with no marks.
  const show = (id: number | null, on = true) => {
    setOpen(null);
    onChange((current) => ({
      ...current,
      marking: on,
      viewing: id,
      snapshots: current.snapshots
        .map((snapshot) => ({ ...snapshot, marks: described(snapshot.marks) }))
        .filter((snapshot) => snapshot.id === id || snapshot.marks.length > 0),
    }));
  };

  const toggle = () => show(null, !marking);

  const remove = (id: number) => {
    setOpen(null);
    onChange((current) => ({
      ...current,
      viewing: current.viewing === id ? null : current.viewing,
      snapshots: current.snapshots.filter((snapshot) => snapshot.id !== id),
    }));
  };

  const discard = () => {
    setOpen(null);
    onChange(() => NO_MARKUP);
  };

  // Where a drag is measured: the snapshot in view, or the live view.
  const target = () => (viewed ? stage.current : surface.current);

  const begin = (event: PointerEvent, next: Gesture) => {
    event.preventDefault();
    surface.current?.setPointerCapture(event.pointerId);
    gesture.current = next;
  };

  const onPress = (event: PointerEvent<HTMLDivElement>) => {
    const element = target();
    if (event.button !== 0 || !element) {
      return;
    }
    if (open !== null) {
      close();
    }
    const from = pointIn(element, event);
    begin(event, { kind: "draw", from });
    setDrawing(boxBetween(from, from));
  };

  const onMarkPress = (event: PointerEvent, mark: Mark) => {
    event.stopPropagation();
    if (event.button !== 0 || !stage.current) {
      return;
    }
    if (open !== mark.id) {
      close();
      setOpen(mark.id);
    }
    begin(event, {
      kind: "move",
      id: mark.id,
      from: pointIn(stage.current, event),
      box: mark,
    });
  };

  const onResizePress = (event: PointerEvent, mark: Mark, corner: Corner) => {
    event.stopPropagation();
    if (event.button !== 0) {
      return;
    }
    begin(event, {
      kind: "resize",
      id: mark.id,
      anchor: oppositeCorner(mark, corner),
    });
  };

  const onDrag = (event: PointerEvent<HTMLDivElement>) => {
    const now = gesture.current;
    const element = target();
    if (!now || !element) {
      return;
    }
    const point = pointIn(element, event);
    if (now.kind === "draw") {
      setDrawing(boxBetween(now.from, point));
      return;
    }
    const box =
      now.kind === "move"
        ? moveBox(now.box, { x: point.x - now.from.x, y: point.y - now.from.y })
        : boxBetween(now.anchor, point);
    if (viewed) {
      changeMarks(viewed.id, (marks) =>
        marks.map((mark) => (mark.id === now.id ? { ...mark, ...box } : mark)),
      );
    }
  };

  const onRelease = (event: PointerEvent<HTMLDivElement>) => {
    const was = gesture.current;
    gesture.current = null;
    const element = target();
    if (was?.kind !== "draw" || !element) {
      return;
    }
    setDrawing(null);
    const box = boxBetween(was.from, pointIn(element, event));
    const rect = element.getBoundingClientRect();
    if (
      event.type === "pointercancel" ||
      box.width * rect.width < SMALLEST ||
      box.height * rect.height < SMALLEST
    ) {
      return;
    }
    const id = nextId(markup);
    if (viewed) {
      changeMarks(viewed.id, (marks) => [...marks, { id, note: "", ...box }]);
      setOpen(id);
      return;
    }
    const still = capture.current?.capture();
    if (!still) {
      setError(
        "Couldn't hold the view still to mark it. Reload the app and try again.",
      );
      return;
    }
    setError(null);
    onChange((current) => ({
      ...current,
      viewing: id,
      snapshots: [
        ...current.snapshots,
        { id, still, marks: [{ id: id + 1, note: "", ...box }] },
      ],
    }));
    setOpen(id + 1);
  };

  const compose = async () => {
    if (count === 0 || composing) {
      return;
    }
    close();
    setError(null);
    setComposing(true);
    try {
      const request = await markupRequest(markup);
      onCompose(markupPrompt(request), markupFiles(request));
      discard();
    } catch (cause) {
      setError(`Couldn't draw the marks. ${describe(cause)}`);
    } finally {
      setComposing(false);
    }
  };

  useShortcuts({
    m: () => {
      if (active) {
        toggle();
      }
    },
    escape: () => {
      if (!active) {
        return;
      }
      if (open !== null) {
        close();
      } else if (marking) {
        toggle();
      }
    },
  });

  const opened = viewed?.marks.find((mark) => mark.id === open);
  return (
    <div className="absolute inset-0 isolate">
      <div
        ref={surface}
        onPointerDown={active && marking ? onPress : undefined}
        onPointerMove={onDrag}
        onPointerUp={onRelease}
        onPointerCancel={onRelease}
        onContextMenu={(event) => event.preventDefault()}
        className={cn(
          "absolute inset-0",
          active && marking && "cursor-crosshair",
        )}
      >
        {children}
        {drawing && !viewed && <Drawing box={drawing} />}
        {viewed && width > 0 && (
          <div
            ref={stage}
            // Keeps the open note's focus through a press on its box or a handle, which only drags.
            onMouseDown={(event) => event.preventDefault()}
            style={{
              width,
              height,
              left: (room.width - width) / 2,
              top: (room.height - height) / 2,
            }}
            // Over the labels the scene puts on the canvas as HTML, like the dimensions, which sit up to z-index 5.
            className="absolute z-10 touch-none bg-canvas select-none"
          >
            <img
              src={viewed.still.url}
              alt={`View of ${model.name} held still to mark up`}
              draggable={false}
              className="pointer-events-none size-full"
            />
            {viewed.marks.map((mark) => (
              <MarkBox
                key={mark.id}
                mark={mark}
                open={mark.id === open}
                width={width}
                height={height}
                onPress={(event) => onMarkPress(event, mark)}
                onResize={(event, corner) => onResizePress(event, mark, corner)}
              />
            ))}
            {drawing && <Drawing box={drawing} />}
            {opened && (
              <Note
                key={opened.id}
                mark={opened}
                place={notePlace(opened, width, height)}
                onChange={(note) =>
                  changeMarks(viewed.id, (marks) =>
                    marks.map((mark) =>
                      mark.id === opened.id ? { ...mark, note } : mark,
                    ),
                  )
                }
                onDone={close}
                onDelete={() => {
                  setOpen(null);
                  changeMarks(viewed.id, (marks) =>
                    marks.filter((mark) => mark.id !== opened.id),
                  );
                }}
              />
            )}
          </div>
        )}
      </div>
      {active && (
        <>
          {/* Framed in the accent while marking, so a drag reads as drawing rather than turning the model. */}
          {marking && (
            <div className="pointer-events-none absolute inset-0 ring-1 ring-accent-ink ring-inset" />
          )}
          <div className="absolute top-3 left-3 z-20 flex items-center gap-1.5">
            {tools}
            <MarkToggle marking={marking} compact={compact} onToggle={toggle} />
          </div>
          {snapshots.length > 0 && (
            <Views
              snapshots={snapshots}
              viewing={markup.viewing}
              onShow={show}
              onRemove={remove}
            />
          )}
          {/* Clear of the axis gizmo in the corner, which the live view shows. */}
          <div
            className={cn(
              "pointer-events-none absolute bottom-3 left-3 z-20 flex flex-col items-center gap-2",
              viewed ? "right-3" : "right-24",
            )}
          >
            {error && (
              <Notice className="pointer-events-auto max-w-120">{error}</Notice>
            )}
            <Bar
              marking={marking}
              marks={count}
              views={ready.length}
              viewed={viewed !== null}
              running={model.status === "running"}
              composing={composing}
              model={model.name}
              message={markup.message}
              onMessage={(message) =>
                onChange((current) => ({ ...current, message }))
              }
              onDiscard={discard}
              onCompose={() => void compose()}
            />
          </div>
        </>
      )}
    </div>
  );
}
