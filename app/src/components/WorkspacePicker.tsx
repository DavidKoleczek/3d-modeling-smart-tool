import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/field";
import { Icon } from "@/components/ui/icon";
import { Notice } from "@/components/ui/notice";
import { Tooltip } from "@/components/ui/tooltip";
import { baseName } from "@/lib/library";
import { cn } from "@/lib/utils";
import {
  chooseFolderForNew,
  chooseWorkspace,
  createWorkspace,
  forgetWorkspace,
  openWorkspace,
  useWorkspaces,
} from "@/lib/workspaces";

/** The folder that holds `path`, as the path to it. */
function parentOf(path: string): string {
  const name = baseName(path);
  return path.slice(0, path.lastIndexOf(name)).replace(/[\\/]$/, "") || path;
}

/** A path cut from the start, since where folders differ is nearest the end. */
function TailPath({ path, className }: { path: string; className?: string }) {
  return (
    <span
      title={path}
      className={cn("truncate text-left [direction:rtl]", className)}
    >
      <bdi>{path}</bdi>
    </span>
  );
}

/**
 * The workspaces opened in the app, newest first, each by its folder's name and path, to switch to; Open Workspace,
 * which shows the folder dialog for another; and New Workspace, which makes a folder for one. One whose folder is gone
 * is marked and can be forgotten.
 */
export function WorkspacePicker({
  onPicked,
  className,
}: {
  /** Once a workspace is picked, whether or not it is another. */
  onPicked?: () => void;
  className?: string;
}) {
  const { workspaces, shown, error, switching } = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const recent = workspaces?.recent ?? [];
  const picked = (switched: boolean) => switched && onPicked?.();
  const open = (path: string) => void openWorkspace(path).then(picked);

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      {recent.length > 0 && (
        <ol aria-label="Recent workspaces" className="flex flex-col">
          {recent.map((workspace) => {
            const name = baseName(workspace.path);
            const current = workspace.path === shown;
            return (
              <li key={workspace.path} className="group/row relative">
                <button
                  type="button"
                  disabled={workspace.missing || switching}
                  onClick={() =>
                    current ? onPicked?.() : open(workspace.path)
                  }
                  aria-current={current ? "true" : undefined}
                  title={workspace.path}
                  className={cn(
                    "flex w-full min-w-0 items-center gap-2.5 rounded-sm py-1.5 pr-9 pl-2 text-left -outline-offset-2",
                    current ? "bg-accent-soft" : "hover:bg-hover",
                    "disabled:hover:bg-transparent",
                  )}
                >
                  <Icon
                    name={workspace.missing ? "warning" : "folder"}
                    className="text-ink-muted"
                  />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span
                      className={cn(
                        "truncate font-medium",
                        workspace.missing && "text-ink-muted",
                      )}
                    >
                      {name}
                    </span>
                    <span className="flex min-w-0 mono-annotation text-ink-muted">
                      {workspace.missing && (
                        <span className="shrink-0">Missing&nbsp;·&nbsp;</span>
                      )}
                      <TailPath path={parentOf(workspace.path)} />
                    </span>
                  </span>
                </button>
                <div
                  className={cn(
                    "absolute top-1/2 right-1.5 -translate-y-1/2",
                    !workspace.missing &&
                      !current &&
                      "opacity-0 group-focus-within/row:opacity-100 group-hover/row:opacity-100",
                  )}
                >
                  {current ? (
                    <Icon name="check" className="mr-1 text-accent-ink" />
                  ) : (
                    <Tooltip content="Forget">
                      <Button
                        size="sm"
                        icon
                        aria-label={`Forget ${name}`}
                        onClick={() => void forgetWorkspace(workspace.path)}
                      >
                        <Icon name="close" />
                      </Button>
                    </Tooltip>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {creating && workspaces ? (
        <NewWorkspace
          folder={workspaces.new_in}
          onMade={() => {
            setCreating(false);
            onPicked?.();
          }}
          onCancel={() => setCreating(false)}
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            variant={recent.length > 0 ? "secondary" : "primary"}
            disabled={switching}
            onClick={() => void chooseWorkspace().then(picked)}
          >
            <Icon name="folder" />
            Open Workspace
          </Button>
          <Button
            variant="secondary"
            disabled={switching || !workspaces}
            onClick={() => setCreating(true)}
          >
            <Icon name="add" />
            New Workspace
          </Button>
        </div>
      )}
      {error && <Notice>{error}</Notice>}
    </div>
  );
}

/** A new workspace: a folder named here, made in `folder` unless Change picks another in the folder dialog. */
function NewWorkspace({
  folder,
  onMade,
  onCancel,
}: {
  folder: string;
  onMade: () => void;
  onCancel: () => void;
}) {
  const { switching } = useWorkspaces();
  const [name, setName] = useState("");
  const [parent, setParent] = useState(folder);
  const id = useId();
  const named = name.trim();

  return (
    <form
      aria-label="New workspace"
      className="flex flex-col gap-2 rounded-md border border-line p-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (named && !switching) {
          void createWorkspace(named, parent).then((made) => made && onMade());
        }
      }}
    >
      <div>
        <Label htmlFor={id}>Name</Label>
        <Input
          id={id}
          // Opened by asking for it, so typing the name comes next.
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="The new folder's name"
          spellCheck={false}
        />
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 text-label text-ink-muted">In</span>
        <TailPath
          path={parent}
          className="min-w-0 flex-1 mono-annotation text-ink-muted"
        />
        <Button
          size="sm"
          disabled={switching}
          onClick={() =>
            void chooseFolderForNew().then(
              (chosen) => chosen !== null && setParent(chosen),
            )
          }
        >
          Change
        </Button>
      </div>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!named || switching}>
          Create
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
