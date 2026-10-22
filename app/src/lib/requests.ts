import { createModel, steerModel, type ModelSummary } from "@/lib/api";
import { providerLabel, type Intelligence } from "@/lib/intelligence";

/** How the person set up the next request on the model in view, which the composer sends with. */
export type NextRequest = {
  intelligence: Intelligence;
  /** Whether they left Continue session on for the model. */
  resume: boolean;
  onResume: (resume: boolean) => void;
};

/** Words and files put into a model's composer from elsewhere in the app, such as marked views, to send from there. */
export type Handoff = {
  id: number;
  model: string;
  text: string;
  files: File[];
};

/** What a request works from: uploads from `upload_reference`, and models in the directory. */
export type WorkFrom = { uploads?: string[]; reference_models?: string[] };

/** Whether the next request on `model` continues its last session, and why or why not, for Continue session. */
export function sessionOf(
  model: ModelSummary,
  next: NextRequest,
): { continuable: boolean; continuing: boolean; hint: string } {
  const { intelligence } = next;
  // A session goes on only with the agent provider it ran on, and only where that agent provider still has it.
  const session = model.last_session;
  const sameProvider =
    !intelligence.choice ||
    intelligence.choice.agent_provider === session?.agent_provider;
  const continuable = session !== null && model.resumable && sameProvider;
  const continuing = next.resume && continuable;
  const ranOn = session && providerLabel(session.agent_provider);
  const fresh = "so this starts a fresh session that reads the model's script";
  const hint = !ranOn
    ? "It has no agent session yet, so this starts one, which reads the model's script"
    : !model.resumable
      ? `Its last session ran on ${ranOn}, which no longer has it on this machine, ${fresh}.`
      : !sameProvider
        ? intelligence.options?.models.some(
            (offered) => offered.agent_provider === session.agent_provider,
          )
          ? `Its last session ran on ${ranOn}, which this AI model can't continue, ${fresh}. Pick a ${ranOn} model to continue it.`
          : `Its last session ran on ${ranOn}, which isn't set up here, ${fresh}.`
        : continuing
          ? "Continues the agent session that last worked on it, which remembers the conversation"
          : "Starts a fresh agent session, which reads the model's script";
  return { continuable, continuing, hint };
}

/**
 * Ask the agent on `model` for `prompt`, with what to work from: as steering while a run works on it, which takes only
 * uploads, else as a request starting a run with the AI model picked, continuing its session as Continue session says.
 */
export async function ask(
  model: ModelSummary,
  next: NextRequest,
  prompt: string,
  from: WorkFrom = {},
): Promise<void> {
  if (model.status === "running") {
    if (from.reference_models?.length) {
      throw new Error(
        "A model to work from goes only with a new request. Remove it to steer, or send it once the run ends.",
      );
    }
    await steerModel(model.name, prompt, from.uploads);
    return;
  }
  await createModel({
    prompt,
    name: model.name,
    resume_session: sessionOf(model, next).continuing,
    ...from,
    ...next.intelligence.choice,
  });
}
