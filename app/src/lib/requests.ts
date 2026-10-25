import {
  colorModel,
  createModel,
  detailModel,
  rigModel,
  steerModel,
  type ModelMode,
  type ModelSummary,
} from "@/lib/api";
import { providerLabel, type Intelligence } from "@/lib/intelligence";

/** Each mode as the app names it. */
export const MODE_LABELS: Record<ModelMode, string> = {
  shape: "Shape",
  rig: "Rig",
  color: "Color",
  detail: "Detail",
};

/** How the person set up the next request on the model in view, which the composer sends with. */
export type NextRequest = {
  intelligence: Intelligence;
  /** The mode the request runs in, which starts as the mode of the model's last run. */
  mode: ModelMode;
  onMode: (mode: ModelMode) => void;
  /** Whether Continue session is on for the model. */
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
        : continuing && session.mode !== next.mode
          ? `Continues the agent session that last worked on it in ${MODE_LABELS[session.mode]}, and gives it the ${MODE_LABELS[next.mode]} instructions`
          : continuing
            ? "Continues the agent session that last worked on it, which remembers the conversation"
            : "Starts a fresh agent session, which reads the model's script";
  return { continuable, continuing, hint };
}

/**
 * Ask the agent on `model` for `prompt`, with what to work from: as steering while a run works on it, which takes only
 * uploads, else as a request starting a run in the mode picked, with the AI model picked, continuing its session as
 * Continue session says. A rig, coloring, or detailing can go without a prompt, which leaves the agent to work it out.
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
  const request = {
    name: model.name,
    resume_session: sessionOf(model, next).continuing,
    ...from,
    ...next.intelligence.choice,
  };
  if (next.mode !== "shape") {
    const start = { rig: rigModel, color: colorModel, detail: detailModel }[
      next.mode
    ];
    await start(prompt ? { prompt, ...request } : request);
    return;
  }
  await createModel({ prompt, ...request });
}
