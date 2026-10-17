import type { CallToolResult } from "@modelcontextprotocol/client";

import { app } from "@/lib/host";

const UPDATES_TOOL = "app_updates";
const LIST_TOOL = "list_3d_models";
const VIEW_TOOL = "view_3d_model";
const MODEL_FILE_PREFIX = "modeling-3d://models/";

export class AppError extends Error {}

/** `ModelStatus` in schemas.py. */
export type ModelStatus =
  "running" | "crashed" | "done" | "failed" | "cancelled" | "timed-out";

/** The fields of `ModelRunRecord` in schemas.py that the view reads. */
export type ModelRun = {
  id: string;
  prompt: string;
  agent_provider: string;
  session_id: string | null;
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
};

/** `ModelListing` in schemas.py. */
export type ModelListing = {
  directory: string;
  models: ModelSummary[];
  last_viewed: string | null;
  unreadable: string[];
};

/** One of a model's files as the server gives it: base64, with its media type. */
export type ModelFile = { base64: string; mimeType: string };

export const GLB = "model.glb";
const RENDER = /^renders\/.+\.(png|jpe?g|webp)$/i;

/** The render a model's thumbnail shows, if the agent has left any. */
export function firstRender(model: ModelSummary): string | undefined {
  return model.files.find((file) => RENDER.test(file));
}

function textOf(result: CallToolResult): string {
  return result.content
    .flatMap((block) => (block.type === "text" ? [block.text] : []))
    .join(" ");
}

async function structuredFrom(
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const result = await app.callServerTool({ name, arguments: args });
  if (result.isError) {
    throw new AppError(textOf(result) || `\`${name}\` failed.`);
  }
  if (!result.structuredContent) {
    throw new AppError(
      `\`${name}\` returned nothing. Check that the server is Modeling 3D.`,
    );
  }
  return result.structuredContent as Record<string, unknown>;
}

/** The models in the app's directory, newest first, and the one viewed last. */
export async function listModels(): Promise<ModelListing> {
  const structured = await structuredFrom(LIST_TOOL, {});
  if (!Array.isArray(structured.models)) {
    throw new AppError(
      `\`${LIST_TOOL}\` returned no models. Check that the server is this version of Modeling 3D.`,
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

/** What the agent has said in the app past the first `after` messages. */
export async function agentMessages(after: number): Promise<string[]> {
  const result = await app.callServerTool({
    name: UPDATES_TOOL,
    arguments: { after },
  });
  if (result.isError) {
    throw new AppError(textOf(result) || `\`${UPDATES_TOOL}\` failed.`);
  }
  const structured = result.structuredContent as
    { messages?: unknown } | undefined;
  if (!Array.isArray(structured?.messages)) {
    throw new AppError(
      `\`${UPDATES_TOOL}\` returned no messages. Check that the server is Modeling 3D.`,
    );
  }
  return structured.messages.filter(
    (message): message is string => typeof message === "string",
  );
}

/** Hand `text` to the host, which delivers it to the agent as the user's message. */
export async function steer(text: string): Promise<void> {
  const result = await app.sendMessage({
    role: "user",
    content: [{ type: "text", text }],
  });
  if (result.isError) {
    throw new AppError("The host did not deliver the message.");
  }
}

export function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}
