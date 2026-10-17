import type { ReasoningEffort } from "@/lib/api";
import { effortLabel, type Intelligence } from "@/lib/intelligence";
import { cn } from "@/lib/utils";

const SELECT =
  "h-7 min-w-0 rounded-lg border border-input bg-transparent px-1.5 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

/** Which AI model runs the next request, and how hard it thinks; the pick is remembered for the directory. */
export function ModelPicker({
  intelligence,
  hint,
  className,
}: {
  intelligence: Intelligence;
  hint?: string;
  className?: string;
}) {
  const { options, choice } = intelligence;
  if (!options || !choice || options.models.length === 0) {
    return null;
  }
  return (
    <span className={cn("flex shrink-0 items-center gap-1", className)}>
      <select
        value={choice.model}
        onChange={(event) =>
          intelligence.choose(event.target.value, choice.reasoning_effort)
        }
        aria-label="AI model"
        title={hint ?? "The AI model the agent runs on"}
        className={SELECT}
      >
        {options.models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.label}
          </option>
        ))}
      </select>
      <select
        value={choice.reasoning_effort}
        onChange={(event) =>
          intelligence.choose(
            choice.model,
            event.target.value as ReasoningEffort,
          )
        }
        aria-label="Reasoning effort"
        title={hint ?? "How hard the AI model thinks before it acts"}
        className={SELECT}
      >
        {options.reasoning_efforts.map((effort) => (
          <option key={effort} value={effort}>
            {effortLabel(effort)}
          </option>
        ))}
      </select>
    </span>
  );
}
