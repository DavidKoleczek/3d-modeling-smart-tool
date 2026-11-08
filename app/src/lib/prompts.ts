import type { AppLibrary, ModelMode, ModelSummary } from "@/lib/api";

const RECENT = 8;

/** A prompt to start from: one the person pinned, or one a model here was last asked. */
export type CannedPrompt = {
  key: string;
  text: string;
  mode: ModelMode;
  /** The model a recent prompt was asked of. */
  model?: string;
};

/** The prompts the person pinned in `mode`, oldest first, so each keeps its place. */
export function pinnedPrompts(
  library: AppLibrary,
  mode: ModelMode,
): CannedPrompt[] {
  return library.prompts
    .filter((prompt) => prompt.mode === mode)
    .map((prompt) => ({ key: `pinned:${prompt.text}`, ...prompt }));
}

/** What the models here were last asked, newest first, each once. */
export function recentPrompts(models: ModelSummary[]): CannedPrompt[] {
  const newest = models
    .flatMap((model) =>
      model.last_run ? [{ model: model.name, run: model.last_run }] : [],
    )
    .sort((a, b) => b.run.started.localeCompare(a.run.started));
  const seen = new Set<string>();
  const prompts: CannedPrompt[] = [];
  for (const { model, run } of newest) {
    const text = run.prompt.trim();
    if (text && !seen.has(text)) {
      seen.add(text);
      prompts.push({ key: `recent:${model}`, text, mode: run.mode, model });
    }
  }
  return prompts.slice(0, RECENT);
}

/**
 * The prompt a new model starts from: what the last model created in the app here was asked, else the newest a model
 * here was shaped from.
 */
export function lastPrompt(
  library: AppLibrary,
  models: ModelSummary[],
): string {
  return (
    library.last_prompt ??
    recentPrompts(models).find((prompt) => prompt.mode === "shape")?.text ??
    ""
  );
}
