import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { Select } from "@/components/ui/select";
import { Tooltip } from "@/components/ui/tooltip";
import type { ReasoningEffort } from "@/lib/api";
import {
  effortLabel,
  providerLabel,
  type Intelligence,
} from "@/lib/intelligence";

/** Which AI model runs the next request, and how hard it thinks, as two fields; the pick is kept for the directory. */
export function ModelFields({ intelligence }: { intelligence: Intelligence }) {
  const { options, choice } = intelligence;
  if (!options || !choice || options.models.length === 0) {
    return null;
  }
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_140px] gap-2">
      <Select
        label="AI model"
        value={choice.model}
        onChange={(model) =>
          intelligence.choose(model, choice.reasoning_effort)
        }
        items={options.models.map((model) => ({
          value: model.id,
          label: model.label,
          group: providerLabel(model.agent_provider),
        }))}
      />
      <Select
        label="Reasoning effort"
        value={choice.reasoning_effort}
        onChange={(effort: ReasoningEffort) =>
          intelligence.choose(choice.model, effort)
        }
        items={options.reasoning_efforts.map((effort) => ({
          value: effort,
          label: effortLabel(effort),
        }))}
      />
    </div>
  );
}

/** The same pick, as one compact menu in the composer, labeled with what the next run will use. */
export function ModelMenu({
  intelligence,
  hint,
}: {
  intelligence: Intelligence;
  hint: string;
}) {
  const { options, choice } = intelligence;
  if (!options || !choice || options.models.length === 0) {
    return null;
  }
  const providers = [
    ...new Set(options.models.map((model) => model.agent_provider)),
  ];
  return (
    <Menu>
      <Tooltip content={hint}>
        <MenuTrigger
          render={<Button size="sm" aria-label="AI model and effort" />}
        >
          <span className="truncate mono-annotation text-ink">
            {intelligence.label(choice.model)} ·{" "}
            {effortLabel(choice.reasoning_effort)}
          </span>
          <Icon name="chevron" className="text-ink-muted" />
        </MenuTrigger>
      </Tooltip>
      <MenuContent side="top" align="end" className="w-56">
        <MenuRadioGroup
          value={choice.model}
          onValueChange={(model: string) =>
            intelligence.choose(model, choice.reasoning_effort)
          }
        >
          {providers.map((provider) => (
            <MenuGroup key={provider}>
              <MenuGroupLabel>{providerLabel(provider)}</MenuGroupLabel>
              {options.models
                .filter((model) => model.agent_provider === provider)
                .map((model) => (
                  <MenuRadioItem key={model.id} value={model.id}>
                    {model.label}
                  </MenuRadioItem>
                ))}
            </MenuGroup>
          ))}
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuRadioGroup
          value={choice.reasoning_effort}
          onValueChange={(effort: ReasoningEffort) =>
            intelligence.choose(choice.model, effort)
          }
        >
          <MenuGroup>
            <MenuGroupLabel>Reasoning effort</MenuGroupLabel>
            {options.reasoning_efforts.map((effort) => (
              <MenuRadioItem key={effort} value={effort}>
                {effortLabel(effort)}
              </MenuRadioItem>
            ))}
          </MenuGroup>
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}
