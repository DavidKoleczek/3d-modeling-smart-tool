import type { Picker } from "@/components/ModelList";
import { ModelThumb } from "@/components/ModelThumb";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { StatusMark } from "@/components/ui/status-mark";
import { shortDirectory } from "@/lib/models";
import { ago } from "@/lib/time";

/** The model list as a menu in the top bar, where there is no room for Your models beside the viewport. */
export function ModelSwitcher({ listing, selected, onSelect, onNew }: Picker) {
  const models = listing?.models ?? [];
  const current = models.find((model) => model.name === selected) ?? null;
  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            size="sm"
            aria-label={current ? `Model: ${current.name}` : "Pick a model"}
            className="min-w-0 pl-0.5"
          />
        }
      >
        {current ? (
          <ModelThumb model={current} size={20} />
        ) : (
          <Icon name="model" className="ml-1" />
        )}
        <span className="min-w-0 truncate text-body font-medium">
          {current?.name ?? "Pick a model"}
        </span>
        <Icon name="chevron" className="text-ink-muted" />
      </MenuTrigger>
      <MenuContent className="w-75 max-w-[calc(100vw-16px)]">
        <div className="max-h-80 overflow-y-auto">
          {models.map((model) => (
            <MenuItem
              key={model.name}
              onClick={() => onSelect(model.name)}
              className="h-12"
            >
              <ModelThumb model={model} size={32} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">{model.name}</span>
                {model.status === "done" ? (
                  <span className="mono-annotation text-ink-muted">
                    {ago(model.updated)}
                  </span>
                ) : (
                  <StatusMark status={model.status} />
                )}
              </span>
              {model.name === selected && (
                <Icon name="check" className="text-accent-ink" />
              )}
            </MenuItem>
          ))}
        </div>
        {models.length > 0 && <MenuSeparator />}
        <MenuItem onClick={onNew}>
          <Icon name="add" />
          <span className="flex-1">New model</span>
          <Kbd>N</Kbd>
        </MenuItem>
        {listing && (
          <>
            <MenuSeparator />
            <p
              title={listing.directory}
              className="flex h-6 items-center truncate px-2 mono-annotation text-ink-muted"
            >
              {shortDirectory(listing.directory)} · {models.length}{" "}
              {models.length === 1 ? "model" : "models"}
            </p>
          </>
        )}
      </MenuContent>
    </Menu>
  );
}
