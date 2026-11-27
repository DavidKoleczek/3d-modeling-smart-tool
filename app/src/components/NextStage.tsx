import { useState } from "react";

import { ModelMenu } from "@/components/ModelPicker";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Segmented } from "@/components/ui/segmented";
import type { ModelMode, ModelSummary } from "@/lib/api";
import { useIntelligence, type Intelligence } from "@/lib/intelligence";
import { MODE_LABELS } from "@/lib/requests";

/**
 * A quiet line over the composer once a run is done, offering the stage that usually comes next, with the AI model to
 * run it. Start sends that mode's default prompt at once; Edit switches the composer to the mode with it in, to change
 * first. A pick of AI model here is the mode's pick in the directory, so the composer shows it too.
 */
export function NextStage({
  model,
  offered,
  busy,
  promptOf,
  onStart,
  onEdit,
}: {
  model: ModelSummary;
  /** The modes to go on to, in order; the last is picked to start with. */
  offered: ModelMode[];
  busy: boolean;
  /** What Start sends in `mode`; null leaves the agent to work it out. */
  promptOf: (mode: ModelMode) => string | null;
  onStart: (mode: ModelMode, intelligence: Intelligence) => void;
  onEdit: (mode: ModelMode) => void;
}) {
  const [picked, setPicked] = useState<ModelMode | null>(null);
  const usual = offered[offered.length - 1];
  const mode = picked !== null && offered.includes(picked) ? picked : usual;
  const intelligence = useIntelligence(model, mode);
  const label = MODE_LABELS[mode];
  const prompt = promptOf(mode);
  return (
    <div
      role="group"
      aria-label="Next stage"
      className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1 pl-0.5"
    >
      <span className="mr-0.5 text-caption text-ink-muted">Next</span>
      {offered.length > 1 ? (
        <Segmented
          label="Next stage"
          size="sm"
          value={mode}
          onChange={setPicked}
          options={offered.map((each) => ({
            value: each,
            label: MODE_LABELS[each],
          }))}
        />
      ) : (
        <span className="text-label text-ink">{label}</span>
      )}
      <ModelMenu
        intelligence={intelligence}
        hint={`Runs ${label}, here and in the composer`}
      />
      <span className="ml-auto flex shrink-0 items-center gap-0.5">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => onEdit(mode)}
          title={`Switch to ${label} with its prompt in, to change before sending`}
        >
          <Icon name="rename" />
          Edit
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => onStart(mode, intelligence)}
          title={
            prompt
              ? `Send now: ${prompt}`
              : `Start ${label} now, leaving the agent to work it out`
          }
        >
          <Icon name="send" />
          Start {label}
        </Button>
      </span>
    </div>
  );
}
