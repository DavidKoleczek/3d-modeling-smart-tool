import type { CallToolResult } from "@modelcontextprotocol/client";

import { app } from "@/lib/host";

const UPDATES_TOOL = "app_updates";

export class AppError extends Error {}

function textOf(result: CallToolResult): string {
  return result.content
    .flatMap((block) => (block.type === "text" ? [block.text] : []))
    .join(" ");
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
