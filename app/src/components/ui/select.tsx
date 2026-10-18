import { Select as SelectPrimitive } from "@base-ui/react/select";
import { Fragment } from "react";

import { Icon } from "@/components/ui/icon";
import { GROUP_LABEL, ITEM, POPUP } from "@/components/ui/popup";
import { cn } from "@/lib/utils";

export type SelectItem<Value extends string> = {
  value: Value;
  label: string;
  /** Items with the same group sit together under it. */
  group?: string;
};

/** A choice of one from a list, in a field: the dialog's AI model and reasoning effort. */
export function Select<Value extends string>({
  value,
  onChange,
  items,
  label,
  disabled = false,
  className,
}: {
  value: Value;
  onChange: (value: Value) => void;
  items: SelectItem<Value>[];
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  const groups = new Map<string, SelectItem<Value>[]>();
  for (const item of items) {
    const group = item.group ?? "";
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return (
    <SelectPrimitive.Root
      value={value}
      onValueChange={(next) => {
        if (next !== null) {
          onChange(next);
        }
      }}
      items={items}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        aria-label={label}
        className={cn(
          "flex h-7 w-full min-w-0 cursor-default items-center gap-2 rounded-sm border border-line-control bg-field px-2 text-left text-body text-ink outline-none select-none focus-visible:border-ink focus-visible:bg-panel focus-visible:focus-ring data-disabled:text-ink-faint data-popup-open:border-ink data-popup-open:bg-panel",
          className,
        )}
      >
        <SelectPrimitive.Value className="min-w-0 flex-1 truncate" />
        <SelectPrimitive.Icon className="text-ink-muted">
          <Icon name="chevron" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Positioner
          alignItemWithTrigger={false}
          sideOffset={4}
          collisionPadding={8}
          className="z-50 outline-none"
        >
          <SelectPrimitive.Popup
            className={cn(POPUP, "min-w-(--anchor-width)")}
          >
            <SelectPrimitive.List className="max-h-(--available-height) overflow-y-auto">
              {[...groups].map(([group, members]) => (
                <Fragment key={group}>
                  {group ? (
                    <SelectPrimitive.Group>
                      <SelectPrimitive.GroupLabel className={GROUP_LABEL}>
                        {group}
                      </SelectPrimitive.GroupLabel>
                      {members.map((item) => (
                        <Option key={item.value} item={item} />
                      ))}
                    </SelectPrimitive.Group>
                  ) : (
                    members.map((item) => (
                      <Option key={item.value} item={item} />
                    ))
                  )}
                </Fragment>
              ))}
            </SelectPrimitive.List>
          </SelectPrimitive.Popup>
        </SelectPrimitive.Positioner>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

function Option<Value extends string>({ item }: { item: SelectItem<Value> }) {
  return (
    <SelectPrimitive.Item value={item.value} className={ITEM}>
      <SelectPrimitive.ItemText className="flex-1">
        {item.label}
      </SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="text-accent-ink">
        <Icon name="check" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}
