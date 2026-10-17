/** `FailureReason` in schemas.py. */
export type FailureReason =
  | "invalid-name"
  | "name-in-use"
  | "no-such-model"
  | "no-such-session"
  | "missing-reference"
  | "no-reference-model"
  | "already-running"
  | "not-running"
  | "provider-mismatch"
  | "agent-unavailable"
  | "start-failed"
  | "bad-cursor"
  | "bad-upload";

/** A failure from the server, with which one it was when the library named it. */
export class AppError extends Error {
  readonly reason: FailureReason | null;
  readonly model: string | null;

  constructor(
    message: string,
    reason: FailureReason | null = null,
    model: string | null = null,
  ) {
    super(message);
    this.reason = reason;
    this.model = model;
  }
}

/**
 * The library's message names commands and arguments for an agent, so each failure it names is worded here for the
 * person, in the app's terms. One without a wording here shows the library's message.
 */
function worded(error: AppError): string | null {
  const model = error.model ?? "That model";
  switch (error.reason) {
    case "invalid-name":
      return "A name can use letters, digits, dots, dashes, and underscores, and starts with a letter or digit.";
    case "name-in-use":
      return `Something that isn't a model is already named ${model} in this folder. Choose another name.`;
    case "no-such-model":
      return `${model} isn't in this folder anymore.`;
    case "no-such-session":
      return `${model} has no agent session like that. Switch Continue session off to change it in a fresh one.`;
    case "missing-reference":
      return "A file to work from couldn't be found. Remove it and add it again.";
    case "no-reference-model":
      return `${model} can't be worked from: it hasn't been built yet, or it's gone.`;
    case "already-running":
      return `${model} is already being worked on. Steer it, or stop it before asking for something new.`;
    case "not-running":
      return `${model} isn't being worked on anymore, so that wasn't sent. Send it again to ask for it as a change.`;
    case "provider-mismatch":
      return `${model}'s last session ran on another agent. Switch off Continue session to change it in a fresh one.`;
    case "agent-unavailable":
      return `The agent couldn't start on this machine. ${error.message}`;
    case "start-failed":
      return "The run couldn't start. Try again; if it keeps failing, run the same request from a terminal to see why.";
    case "bad-upload":
      return "A file didn't arrive whole. Remove it and add it again.";
    default:
      return null;
  }
}

/** What went wrong, for the person. */
export function describe(cause: unknown): string {
  if (cause instanceof AppError) {
    return worded(cause) ?? cause.message;
  }
  return cause instanceof Error ? cause.message : String(cause);
}
