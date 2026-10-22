/** A box as fractions of the still's width and height, from its top left corner. */
export type Box = { x: number; y: number; width: number; height: number };

/** A box the person drew over a view, and what they want changed inside it. */
export type Mark = Box & { id: number; note: string };

/** The view as it was when the person first marked it, in device pixels at `scale` to CSS pixels. */
export type Still = {
  url: string;
  width: number;
  height: number;
  scale: number;
};

/** A view held still the moment the person first marked it, and every mark they drew on it since. */
export type Snapshot = { id: number; still: Still; marks: Mark[] };

/**
 * What the person is putting together for a model's agent: the views they marked, in order, the one they are on, or
 * null for the live view, and anything else they want to say. While `marking`, a drag draws a box rather than turning
 * the model.
 */
export type Markup = {
  snapshots: Snapshot[];
  viewing: number | null;
  message: string;
  marking: boolean;
};

export const NO_MARKUP: Markup = {
  snapshots: [],
  viewing: null,
  message: "",
  marking: false,
};

/** What goes to the agent, in order: each view with its marks drawn on and their notes, then the message. */
export type MarkupRequest = {
  views: { image: string; text: string }[];
  message: string;
};

export type Point = { x: number; y: number };

export type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

export const CORNERS: Corner[] = [
  "top-left",
  "top-right",
  "bottom-left",
  "bottom-right",
];

function clamp(value: number, low = 0, high = 1): number {
  return Math.min(high, Math.max(low, value));
}

/** The point of `event` as fractions of `element`, kept inside it. */
export function pointIn(
  element: HTMLElement,
  event: { clientX: number; clientY: number },
): Point {
  const rect = element.getBoundingClientRect();
  return {
    x: clamp((event.clientX - rect.left) / rect.width),
    y: clamp((event.clientY - rect.top) / rect.height),
  };
}

/** The box with corners at `a` and `b`, whichever way it was dragged. */
export function boxBetween(a: Point, b: Point): Box {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  };
}

/** `box` moved by `by`, stopping at the edges so it keeps its size. */
export function moveBox(box: Box, by: Point): Box {
  return {
    ...box,
    x: clamp(box.x + by.x, 0, 1 - box.width),
    y: clamp(box.y + by.y, 0, 1 - box.height),
  };
}

/** The corner of `box` across from `corner`, which stays put while `corner` is dragged. */
export function oppositeCorner(box: Box, corner: Corner): Point {
  return {
    x: corner.endsWith("left") ? box.x + box.width : box.x,
    y: corner.startsWith("top") ? box.y + box.height : box.y,
  };
}

/** The marks with something written in them; a mark left empty is dropped rather than sent. */
export function described(marks: Mark[]): Mark[] {
  return marks.filter((mark) => mark.note.trim());
}

/** The snapshots with their described marks, leaving out any with none. */
export function marked(snapshots: Snapshot[]): Snapshot[] {
  return snapshots
    .map((snapshot) => ({ ...snapshot, marks: described(snapshot.marks) }))
    .filter((snapshot) => snapshot.marks.length > 0);
}

/** An id no snapshot or mark in `markup` has yet. */
export function nextId(markup: Markup): number {
  const ids = markup.snapshots.flatMap((snapshot) => [
    snapshot.id,
    ...snapshot.marks.map((mark) => mark.id),
  ]);
  return Math.max(0, ...ids) + 1;
}

function token(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--${name}`)
    .trim();
}

/**
 * The still with each mark drawn on it, numbered from `first`, and which of `count` views it is in its top left corner,
 * as a PNG data URL. The view shows neither, but the agent needs them to tell which note goes with which box, and
 * which words with which image.
 */
async function drawMarks(
  still: Still,
  marks: Mark[],
  first: number,
  index: number,
  count: number,
): Promise<string> {
  const image = new Image();
  image.src = still.url;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = still.width;
  canvas.height = still.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error(
      "This browser could not draw the marks. Try again, or reload the app.",
    );
  }
  const unit = still.scale;
  const ink = token("accent-ink");
  const font = (size: number) =>
    `600 ${size * unit}px "Geist Mono Variable", ui-monospace, monospace`;
  context.drawImage(image, 0, 0);
  context.font = font(22);
  context.textAlign = "center";
  context.textBaseline = "middle";
  marks.forEach((mark, index) => {
    const x = mark.x * canvas.width;
    const y = mark.y * canvas.height;
    const width = mark.width * canvas.width;
    const height = mark.height * canvas.height;
    context.fillStyle = ink;
    context.globalAlpha = 0.12;
    context.fillRect(x, y, width, height);
    context.globalAlpha = 1;
    context.lineWidth = 5 * unit;
    context.strokeStyle = ink;
    context.strokeRect(x, y, width, height);
    const badge = 36 * unit;
    // Flush with the outline's outer edge, which is centered on the box's.
    const edge = context.lineWidth / 2;
    // Above the box, or just inside it where the top edge leaves no room.
    const top = y >= badge ? y - badge : y;
    context.fillStyle = ink;
    context.fillRect(x - edge, top, badge, badge);
    context.fillStyle = token("panel");
    context.fillText(
      String(first + index),
      x - edge + badge / 2,
      top + badge / 2,
    );
  });
  // Over any mark beneath it, so it always reads.
  const label = `View ${index + 1} of ${count}`;
  const margin = 16 * unit;
  const padding = 14 * unit;
  context.font = font(28);
  context.textAlign = "left";
  const height = 50 * unit;
  context.fillStyle = token("ink");
  context.fillRect(
    margin,
    margin,
    context.measureText(label).width + 2 * padding,
    height,
  );
  context.fillStyle = token("panel");
  context.fillText(label, margin + padding, margin + height / 2);
  return canvas.toDataURL("image/png");
}

/** What goes with a view's image: which view it is, as its image says too, and its notes, numbered as its boxes are. */
function viewText(
  marks: Mark[],
  first: number,
  index: number,
  count: number,
): string {
  return [
    `View ${index + 1} of ${count}. Change what is inside each numbered box:`,
    ...marks.map((mark, at) => `${first + at}. ${mark.note.trim()}`),
  ].join("\n");
}

/** What the agent gets for `markup`: each marked view, drawn on and described, then the message. */
export async function markupRequest(markup: Markup): Promise<MarkupRequest> {
  const snapshots = marked(markup.snapshots);
  const views: MarkupRequest["views"] = [];
  let first = 1;
  for (const [index, snapshot] of snapshots.entries()) {
    views.push({
      image: await drawMarks(
        snapshot.still,
        snapshot.marks,
        first,
        index,
        snapshots.length,
      ),
      text: viewText(snapshot.marks, first, index, snapshots.length),
    });
    first += snapshot.marks.length;
  }
  return { views, message: markup.message.trim() };
}

/** The marked views of `request` as image files to attach, each named for the view it is. */
export function markupFiles(request: MarkupRequest): File[] {
  return request.views.map((view, index) => {
    const [header = "", data = ""] = view.image.split(",", 2);
    const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
    const type = /^data:([^;,]+)/.exec(header)?.[1] ?? "image/png";
    return new File([bytes], `marked-view-${index + 1}.png`, { type });
  });
}

/** The words of `request` for the agent: each view's, in the order their images go with them, then the message. */
export function markupPrompt(request: MarkupRequest): string {
  return [...request.views.map((view) => view.text), request.message]
    .filter(Boolean)
    .join("\n\n");
}
