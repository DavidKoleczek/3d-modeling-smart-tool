import type { CallToolResult } from "@modelcontextprotocol/client";

import { AppError, type FailureReason } from "@/lib/errors";
import { app } from "@/lib/host";

const LIST_TOOL = "list_3d_models";
const VIEW_TOOL = "view_3d_model";
const CREATE_TOOL = "create_3d_model";
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

/** `ModelStatus` in schemas.py. */
export type ModelStatus =
  "running" | "crashed" | "done" | "failed" | "cancelled" | "timed-out";

/** `ReasoningEffort` in schemas.py. */
export type ReasoningEffort =
  "low" | "medium" | "high" | "xhigh" | "max" | "ultra";

/** The fields of `ModelRunRecord` in schemas.py that the view reads. */
export type ModelRun = {
  id: string;
  prompt: string;
  agent_provider: string;
  model: string;
  reasoning_effort: ReasoningEffort;
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
  status: ModelStatus | null;
  last_run: ModelRun | null;
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
  resume_session?: boolean | string;
  uploads?: string[];
  reference_models?: string[];
} & Partial<IntelligenceChoice>;

/** One of a model's files as the server gives it: base64, with its media type. */
export type ModelFile = { base64: string; mimeType: string };

export const GLB = "model.glb";
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

/** Send a piece of a file to work from, `data` in base64, to land at `offset` in `path` of the upload. */
export async function uploadReference(
  upload: string,
  path: string,
  offset: number,
  data: string,
): Promise<void> {
  await call(UPLOAD_TOOL, { upload, path, offset, data });
}

/** Tell the agent working on `name` something, as the person in the app. */
export async function steerModel(name: string, message: string): Promise<void> {
  await call(STEER_TOOL, { name, message });
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
