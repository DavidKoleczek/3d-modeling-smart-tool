import { Box, FileText, Paperclip, X } from "lucide-react";
import { useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { ModelSummary } from "@/lib/api";
import { referable, type Attachments } from "@/lib/attachments";

/** The picker for files to work from, and the menu of the directory's models to work from. */
export function AttachButtons({
  attachments,
  models,
  exclude,
}: {
  attachments: Attachments;
  models: ModelSummary[];
  exclude?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const choices = referable(models).filter(
    (model) =>
      model.name !== exclude && !attachments.models.includes(model.name),
  );

  return (
    <div className="flex min-w-0 items-center gap-1">
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? []);
          event.target.value = "";
          void attachments.addFiles(picked);
        }}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Attach images or models"
        title="Attach images or models; you can also drop or paste them"
        onClick={() => input.current?.click()}
      >
        <Paperclip />
      </Button>
      {choices.length > 0 && (
        <select
          aria-label="Work from a model"
          value=""
          onChange={(event) => attachments.addModel(event.target.value)}
          className="h-7 max-w-32 min-w-0 rounded-lg border border-input bg-background px-1.5 text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <option value="" disabled>
            Add a model
          </option>
          {choices.map((model) => (
            <option key={model.name} value={model.name}>
              {model.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function Chip({
  label,
  icon,
  onRemove,
}: {
  label: string;
  icon: ReactNode;
  onRemove: () => void;
}) {
  return (
    <li className="flex max-w-full items-center gap-1 rounded-md border bg-muted py-0.5 pr-0.5 pl-1 text-xs">
      {icon}
      <span className="max-w-32 truncate" title={label}>
        {label}
      </span>
      <button
        type="button"
        aria-label={`Remove ${label}`}
        onClick={onRemove}
        className="rounded p-0.5 text-muted-foreground outline-none hover:bg-background hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <X className="size-3" />
      </button>
    </li>
  );
}

/** What a request will work from, each of which can be taken off again. */
export function AttachmentList({ attachments }: { attachments: Attachments }) {
  if (attachments.files.length === 0 && attachments.models.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {attachments.files.map((file, index) => (
        <Chip
          key={`${index}-${file.upload.name}`}
          label={file.upload.name}
          icon={
            file.preview ? (
              <img
                src={file.preview}
                alt=""
                className="size-5 rounded-sm object-cover"
              />
            ) : (
              <FileText className="size-3.5 text-muted-foreground" />
            )
          }
          onRemove={() => attachments.removeFile(index)}
        />
      ))}
      {attachments.models.map((name) => (
        <Chip
          key={name}
          label={name}
          icon={<Box className="size-3.5 text-primary" />}
          onRemove={() => attachments.removeModel(name)}
        />
      ))}
    </ul>
  );
}
