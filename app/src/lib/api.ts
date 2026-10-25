import type { CallToolResult } from "@modelcontextprotocol/client";

import { AppError, type FailureReason } from "@/lib/errors";
import { app } from "@/lib/host";

const LIST_TOOL = "list_3d_models";
const VIEW_TOOL = "view_3d_model";
const CREATE_TOOL = "create_3d_model";
const RIG_TOOL = "rig_3d_model";
const COLOR_TOOL = "color_3d_model";
const DETAIL_TOOL = "detail_3d_model";
const CHECK_TOOL = "check_3d_model";
const UPLOAD_TOOL = "upload_reference";
const STEER_TOOL = "steer_3d_model";
const CANCEL_TOOL = "cancel_3d_model";
const ACTIVITY_TOOL = "read_3d_model_activity";
const TOOL_CALL_TOOL = "read_3d_model_tool_call";
const LIST_INTELLIGENCE_TOOL = "list_intelligence_models";
const CHOOSE_INTELLIGENCE_TOOL = "choose_intelligence_model";
const READ_SETTINGS_TOOL = "read_app_settings";
const SAVE_SETTINGS_TOOL = "save_app_settings";
const READ_FOLDERS_TOOL = "read_app_folders";
const OPEN_FOLDER_TOOL = "open_app_folder";
const MODEL_FILE_PREFIX = "modeling-3d://models/";
// Starting a run waits for its agent to start, which can take a while on a cold machine.
const CREATE_TIMEOUT_MS = 120_000;
// Longer than the server waits on a check before it says the check is still going.
const CHECK_TIMEOUT_MS = 60_000;

/** `ModelStatus` in schemas.py. */
export type ModelStatus =
  "running" | "crashed" | "done" | "failed" | "cancelled" | "timed-out";

/** `ModelMode` in schemas.py: the stage a run works on the model in, each a capability of its own. */
export type ModelMode = "shape" | "rig" | "color" | "detail";

/** `ReasoningEffort` in schemas.py. */
export type ReasoningEffort =
  "low" | "medium" | "high" | "xhigh" | "max" | "ultra";

/** The fields of `ModelRunRecord` in schemas.py that the view reads. */
export type ModelRun = {
  id: string;
  mode: ModelMode;
  /** Empty for a rig, coloring, or detailing left to work it out. */
  prompt: string;
  agent_provider: string;
  model: string;
  reasoning_effort: ReasoningEffort;
  max_triangles: number | null;
  max_draw_calls: number | null;
  /** The smallest and largest the model is on screen, in pixels along its longest side at 1080p. */
  screen_size: [number, number] | null;
  session_id: string | null;
  origin: string | null;
  resumed: boolean;
  started: string;
  finished: string | null;
};

/** `ModelSummary` in schemas.py. */
export type ModelSummary = {
  name: string;
  id: string;
  directory: string;
  created: string;
  updated: string;
  built: string | null;
  /** When its latest check, checks/report.json, was written. */
  checked: string | null;
  status: ModelStatus | null;
  last_run: ModelRun | null;
  /** The latest run with a session, the one a request continues when it resumes. */
  last_session: ModelRun | null;
  /** Whether a run on this machine can continue `last_session`. */
  resumable: boolean;
  files: string[];
  references: string[];
};

/** `ModelListing` in schemas.py. */
export type ModelListing = {
  directory: string;
  models: ModelSummary[];
  last_viewed: string | null;
  unreadable: string[];
};

/** `ActivityKind` in schemas.py. */
export type ActivityKind =
  | "request"
  | "said"
  | "reasoning"
  | "thought"
  | "composing"
  | "tool"
  | "tool-result"
  | "usage"
  | "steered"
  | "checked"
  | "ended";

/** `ActivityEntry` in schemas.py. */
export type ActivityEntry = {
  time: string;
  run_id: string;
  kind: ActivityKind;
  text: string;
  origin: string | null;
  data: Record<string, unknown>;
};

/** `ModelActivity` in schemas.py. */
export type ModelActivity = {
  model: ModelSummary;
  entries: ActivityEntry[];
  cursor: string;
};

/** `CheckName` in schemas.py. */
export type CheckName =
  | "triangles"
  | "sub-pixel"
  | "round-parts"
  | "buried-faces"
  | "on-screen"
  | "draw-calls"
  | "static-parts"
  | "moving-parts"
  | "skeleton"
  | "markers"
  | "poses"
  | "palette"
  | "face-roles"
  | "emission"
  | "schemes"
  | "detail-texture"
  | "detail-uvs"
  | "detail-colors"
  | "detail-renders";

/** `CHECK_GROUPS` in schemas.py, in the order the report gives them. */
export const CHECK_GROUPS: { group: string; checks: CheckName[] }[] = [
  {
    group: "Shape",
    checks: [
      "triangles",
      "sub-pixel",
      "round-parts",
      "buried-faces",
      "on-screen",
    ],
  },
  {
    group: "Rig",
    checks: [
      "draw-calls",
      "static-parts",
      "moving-parts",
      "skeleton",
      "markers",
      "poses",
    ],
  },
  {
    group: "Color",
    checks: ["palette", "face-roles", "emission", "schemes"],
  },
  {
    group: "Detail",
    checks: ["detail-texture", "detail-uvs", "detail-colors", "detail-renders"],
  },
];

/** `CheckResult` in schemas.py: what one check measured, for whoever reads it to judge. */
export type CheckResult = {
  name: CheckName;
  summary: string;
  skipped: boolean;
  lines: string[];
  figures: Record<string, unknown>;
  /** Its renders, relative to the model's directory. */
  files: string[];
};

/** `ModelCheck` in schemas.py. */
export type ModelCheck = {
  name: string;
  directory: string;
  checked: string;
  glb_sha256: string;
  max_triangles: number | null;
  max_draw_calls: number | null;
  screen_size: [number, number] | null;
  /** In meters, along glTF's x, y, and z. */
  dimensions: [number, number, number];
  bounds: [[number, number, number], [number, number, number]];
  triangles: number;
  mesh_objects: number;
  materials: number;
  checks: CheckResult[];
};

/** `ToolCall` in schemas.py. */
export type ToolCall = {
  name: string;
  input: Record<string, unknown>;
  output: string | null;
  failed: boolean;
};

/** `IntelligenceModel` in schemas.py. */
export type IntelligenceModel = {
  agent_provider: string;
  id: string;
  label: string;
  reasoning_efforts: ReasoningEffort[];
};

/** `IntelligenceChoice` in schemas.py. */
export type IntelligenceChoice = {
  agent_provider: string;
  model: string;
  reasoning_effort: ReasoningEffort;
};

/** `AppIntelligence` in schemas.py. */
export type AppIntelligence = {
  models: IntelligenceModel[];
  default: IntelligenceChoice;
  chosen: IntelligenceChoice | null;
};

/** `PaneLayout` in schemas.py. */
export type PaneLayout = { size: number | null; open: boolean };

/** `AppLayout` in schemas.py. */
export type AppLayout = { models: PaneLayout; activity: PaneLayout };

/** `AppSettings` in schemas.py. */
export type AppSettings = {
  theme: "system" | "light" | "dark";
  grid: boolean;
  wireframe: boolean;
  dimensions: boolean;
  rig: boolean;
  surface: boolean;
  wide: AppLayout;
  medium: AppLayout;
  /** By model id, the groups of steps in its activity the person opened or closed, and which. */
  steps: Record<string, Record<string, boolean>>;
};

/** `AppFolders` in schemas.py. */
export type AppFolders = { settings: string; models: string };

/** What a request on a model asks for; a name a model has already changes that model. */
export type ModelRequest = {
  prompt: string;
  name: string;
  /** Left out for the default, or the model's own for a change; null for no budget. */
  max_triangles?: number | null;
  max_draw_calls?: number | null;
  screen_size?: [number, number] | null;
  resume_session?: boolean | string;
  uploads?: string[];
  reference_models?: string[];
} & Partial<IntelligenceChoice>;

/** What a request to rig, color, or detail a built model asks for; it works to the model's own budgets. */
export type BuiltModelRequest = {
  /** Left out, the agent works out what moves, the roles and colors, or what to paint. */
  prompt?: string;
  name: string;
  resume_session?: boolean | string;
  uploads?: string[];
  reference_models?: string[];
} & Partial<IntelligenceChoice>;

/** One of a model's files as the server gives it: base64, with its media type. */
export type ModelFile = { base64: string; mimeType: string };

export const GLB = "model.glb";
const CHECK_REPORT = "checks/report.json";
const RENDER = /^renders\/.+\.(png|jpe?g|webp)$/i;

// The views the agent usually renders, in the order the app shows them; others follow by name.
const VIEWS = ["three_quarter", "front", "side", "back", "top"];

/** The renders the agent left, three-quarter view first. */
export function rendersOf(model: ModelSummary): string[] {
  const rank = (file: string) => {
    const view = VIEWS.indexOf(
      file.replace(/^renders\//, "").replace(/\.\w+$/, ""),
    );
    return view === -1 ? VIEWS.length : view;
  };
  return model.files
    .filter((file) => RENDER.test(file))
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** The render a model's thumbnail shows, if the agent has left any. */
export function firstRender(model: ModelSummary): string | undefined {
  return rendersOf(model)[0];
}

function textOf(result: CallToolResult): string {
  return result.content
    .flatMap((block) => (block.type === "text" ? [block.text] : []))
    .join(" ");
}

async function call(
  name: string,
  args: Record<string, unknown>,
  timeout?: number,
): Promise<CallToolResult> {
  const result = await app.callServerTool(
    { name, arguments: args },
    timeout ? { timeout } : undefined,
  );
  if (result.isError) {
    const failure = result.structuredContent as
      { reason?: FailureReason | null; model?: string | null } | undefined;
    throw new AppError(
      textOf(result) || `\`${name}\` failed.`,
      failure?.reason ?? null,
      failure?.model ?? null,
    );
  }
  return result;
}

async function structuredFrom(
  name: string,
  args: Record<string, unknown>,
  timeout?: number,
): Promise<Record<string, unknown>> {
  const result = await call(name, args, timeout);
  if (!result.structuredContent) {
    throw new AppError(
      `\`${name}\` returned nothing. Check that the server is 3D Modeling.`,
    );
  }
  return result.structuredContent as Record<string, unknown>;
}

/** The models in the app's directory, newest first, and the one viewed last. */
export async function listModels(): Promise<ModelListing> {
  const structured = await structuredFrom(LIST_TOOL, {});
  if (!Array.isArray(structured.models)) {
    throw new AppError(
      `\`${LIST_TOOL}\` returned no models. Check that the server is this version of 3D Modeling.`,
    );
  }
  return structured as ModelListing;
}

/** Record `name` as the model viewed last, so the app opens on it next time. */
export async function viewModel(name: string): Promise<ModelSummary> {
  return (await structuredFrom(VIEW_TOOL, { name })) as ModelSummary;
}

/** One of a model's files, `path` relative to its directory, read through the host. */
export async function readModelFile(
  name: string,
  path: string,
): Promise<ModelFile> {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const uri = `${MODEL_FILE_PREFIX}${encodeURIComponent(name)}/${encoded}`;
  const result = await app.readServerResource({ uri });
  const content = result.contents[0];
  if (!content || !("blob" in content)) {
    throw new AppError(`${uri} came back without its file.`);
  }
  return { base64: content.blob, mimeType: content.mimeType ?? "" };
}

/** Start a run that creates the model, or changes it when it exists; resolves with its summary once its agent runs. */
export async function createModel(
  request: ModelRequest,
): Promise<ModelSummary> {
  return (await structuredFrom(
    CREATE_TOOL,
    request,
    CREATE_TIMEOUT_MS,
  )) as ModelSummary;
}

/** Start a run that rigs the built model; resolves with its summary once its agent runs. */
export async function rigModel(
  request: BuiltModelRequest,
): Promise<ModelSummary> {
  return (await structuredFrom(
    RIG_TOOL,
    request,
    CREATE_TIMEOUT_MS,
  )) as ModelSummary;
}

/** Start a run that colors the built model by role; resolves with its summary once its agent runs. */
export async function colorModel(
  request: BuiltModelRequest,
): Promise<ModelSummary> {
  return (await structuredFrom(
    COLOR_TOOL,
    request,
    CREATE_TIMEOUT_MS,
  )) as ModelSummary;
}

/** Start a run that paints the built model's surface detail; resolves with its summary once its agent runs. */
export async function detailModel(
  request: BuiltModelRequest,
): Promise<ModelSummary> {
  return (await structuredFrom(
    DETAIL_TOOL,
    request,
    CREATE_TIMEOUT_MS,
  )) as ModelSummary;
}

/** Check the model against its own budgets, asking again while the server says the check is still going. */
export async function checkModel(name: string): Promise<ModelCheck> {
  for (;;) {
    const structured = await structuredFrom(
      CHECK_TOOL,
      { name },
      CHECK_TIMEOUT_MS,
    );
    if (structured.report) {
      return structured.report as ModelCheck;
    }
  }
}

/** The model's latest check, as checks/report.json keeps it. */
export async function readCheck(name: string): Promise<ModelCheck> {
  const file = await readModelFile(name, CHECK_REPORT);
  const bytes = Uint8Array.from(atob(file.base64), (character) =>
    character.charCodeAt(0),
  );
  return JSON.parse(new TextDecoder().decode(bytes)) as ModelCheck;
}

/** Send a piece of a file to work from, `data` in base64, to land at `offset` in `path` of the upload. */
export async function uploadReference(
  upload: string,
  path: string,
  offset: number,
  data: string,
): Promise<void> {
  await call(UPLOAD_TOOL, { upload, path, offset, data });
}

/** Tell the agent working on `name` something, as the person in the app, with any uploads to send with it. */
export async function steerModel(
  name: string,
  message: string,
  uploads: string[] = [],
): Promise<void> {
  await call(
    STEER_TOOL,
    uploads.length ? { name, message, uploads } : { name, message },
  );
}

/** Stop the run working on `name`; its session can still be resumed. */
export async function cancelModel(name: string): Promise<void> {
  await call(CANCEL_TOOL, { name });
}

/** The model's summary and its activity, or only what came after `after`. */
export async function readActivity(
  name: string,
  after?: string,
): Promise<ModelActivity> {
  const structured = await structuredFrom(
    ACTIVITY_TOOL,
    after ? { name, after } : { name },
  );
  if (!Array.isArray(structured.entries)) {
    throw new AppError(
      `\`${ACTIVITY_TOOL}\` returned no entries. Check that the server is this version of 3D Modeling.`,
    );
  }
  return structured as ModelActivity;
}

/** One tool call of the agent on `name` in full, by the run and id of its entry in the activity. */
export async function readToolCall(
  name: string,
  runId: string,
  callId: string,
): Promise<ToolCall> {
  return (await structuredFrom(TOOL_CALL_TOOL, {
    name,
    run_id: runId,
    call_id: callId,
  })) as ToolCall;
}

/** The AI models and reasoning efforts to pick from, and the ones picked last in the app's directory. */
export async function listIntelligenceModels(): Promise<AppIntelligence> {
  return (await structuredFrom(LIST_INTELLIGENCE_TOOL, {})) as AppIntelligence;
}

/** Remember the model and effort as the ones picked last, so the app starts on them next time. */
export async function chooseIntelligenceModel(
  model: string,
  reasoningEffort: ReasoningEffort,
): Promise<AppIntelligence> {
  return (await structuredFrom(CHOOSE_INTELLIGENCE_TOOL, {
    model,
    reasoning_effort: reasoningEffort,
  })) as AppIntelligence;
}

/** How the person set up the app, the same in every directory. */
export async function readAppSettings(): Promise<AppSettings> {
  return (await structuredFrom(READ_SETTINGS_TOOL, {})) as AppSettings;
}

/** Keep the app's settings for the person, replacing the ones kept before. */
export async function saveAppSettings(
  settings: AppSettings,
): Promise<AppSettings> {
  return (await structuredFrom(SAVE_SETTINGS_TOOL, {
    settings,
  })) as AppSettings;
}

/** Where the app keeps the person's settings, and the models it shows. */
export async function readAppFolders(): Promise<AppFolders> {
  return (await structuredFrom(READ_FOLDERS_TOOL, {})) as AppFolders;
}

/** Show the folder of the person's settings, of the models here, or of the model `name` in their file manager. */
export async function openAppFolder(
  folder: "settings" | "models" | "model",
  name?: string,
): Promise<void> {
  await call(
    OPEN_FOLDER_TOOL,
    name === undefined ? { folder } : { folder, name },
  );
}
