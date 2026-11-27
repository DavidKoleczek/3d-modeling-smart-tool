import { Checkbox } from "@base-ui/react/checkbox";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Notice } from "@/components/ui/notice";
import { Segmented } from "@/components/ui/segmented";
import {
  listSkillAgents,
  type SkillAgent,
  type SkillAgents,
  type SkillMode,
} from "@/lib/api";
import { AppError, describe } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { dropSkill, refreshWindowsApp, setSkill } from "@/lib/windowsApp";

// The agents named on the shared folder's row, before how many more there are.
const SHOWN_SHARING = 5;
// The first listing gets the skills CLI ready, which is said once it has taken this long.
const LONG_MS = 4000;
const NOTHING_TO_LINK =
  "Nothing to link: every agent chosen reads the shared folder.";

/** A folder under the person's own, as `~` and the rest. */
function shortFolder(folder: string, home: string): string {
  return folder.toLowerCase().startsWith(home.toLowerCase())
    ? `~${folder.slice(home.length)}`
    : folder;
}

/** Those found on this computer first, then by name. */
function inOrder(agents: SkillAgent[], installed: Set<string>): SkillAgent[] {
  const first = (agent: SkillAgent) =>
    installed.has(agent.id) || agent.detected ? 0 : 1;
  return [...agents].sort(
    (one, other) =>
      first(one) - first(other) ||
      one.name.localeCompare(other.name, undefined, { sensitivity: "base" }),
  );
}

/** The agents sharing the folder, by name, then how many more there are. */
function sharedBy(names: string[], more: number): string {
  return more > 0 ? `${names.join(", ")}, and ${more} more` : names.join(", ");
}

function AgentRow({
  name,
  folder,
  tag,
  checked,
  locked = false,
  also,
  onChange,
}: {
  name: string;
  folder: string;
  tag: string | null;
  checked: boolean;
  locked?: boolean;
  also?: string;
  onChange?: (checked: boolean) => void;
}) {
  return (
    <label
      className={cn(
        "grid min-h-7 cursor-default grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-x-2.5 rounded-sm px-2 py-1",
        checked ? "text-ink" : "text-ink-muted",
        !locked && "hover:bg-hover",
      )}
    >
      <Checkbox.Root
        checked={checked}
        disabled={locked}
        onCheckedChange={(next) => onChange?.(next)}
        className="flex size-3.5 items-center justify-center rounded-[3px] border border-line-control bg-field focus-visible:focus-ring data-checked:border-accent data-checked:bg-accent data-disabled:opacity-60"
      >
        <Checkbox.Indicator className="text-on-accent">
          <Icon name="check" className="size-3" />
        </Checkbox.Indicator>
      </Checkbox.Root>
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0">{name}</span>
        <span className="truncate mono-annotation text-ink-muted">
          {folder}
        </span>
      </span>
      {tag ? (
        <span
          className={cn(
            "rounded-[3px] px-1.5 text-caption",
            locked ? "bg-field text-ink-muted" : "bg-accent-soft text-ink",
          )}
        >
          {tag}
        </span>
      ) : (
        <span />
      )}
      {also && (
        <span className="col-span-2 col-start-2 text-caption text-ink-muted">
          {also}
        </span>
      )}
    </label>
  );
}

/** The agents the Windows app's Agent Skill is installed for, chosen as setup chooses them. */
export function SkillDialog({
  installed,
  installedMode,
  onClose,
}: {
  /** Whether the skill is installed, so its agents are the ones ticked. */
  installed: boolean;
  installedMode: SkillMode;
  onClose: () => void;
}) {
  const [listed, setListed] = useState<SkillAgents | null>(null);
  const [notListed, setNotListed] = useState<string | null>(null);
  const [long, setLong] = useState(false);
  const [tries, setTries] = useState(0);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<SkillMode>(installedMode);
  const [filter, setFilter] = useState("");
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => setLong(true), LONG_MS);
    listSkillAgents()
      .then(
        (agents) => {
          if (!current) return;
          const has = new Set(agents.installed);
          const ticked = agents.agents.filter(
            (agent) =>
              !agent.shares && (installed ? has.has(agent.id) : agent.detected),
          );
          setChosen(new Set(ticked.map((agent) => agent.id)));
          setListed(agents);
        },
        (cause: unknown) => {
          if (current) {
            setNotListed(
              cause instanceof AppError
                ? describe(cause)
                : "The agents couldn't be listed. The skills CLI may still be getting ready, so try again in a moment.",
            );
          }
        },
      )
      .finally(() => clearTimeout(timer));
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [tries, installed]);

  const tryAgain = () => {
    setNotListed(null);
    setLong(false);
    setTries((count) => count + 1);
  };
  const finish = (changing: Promise<void>) => {
    setProblem(null);
    setWorking(true);
    changing.then(onClose, (cause: unknown) => {
      setWorking(false);
      setProblem(describe(cause));
      // What did change shows in the menu.
      void refreshWindowsApp();
    });
  };
  const toggle = (id: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(id);
    else next.delete(id);
    setChosen(next);
  };

  const looked = filter.trim().toLowerCase();
  const has = new Set(listed?.installed ?? []);
  const sharing = inOrder(
    listed?.agents.filter((agent) => agent.shares) ?? [],
    has,
  );
  const own = inOrder(
    listed?.agents.filter((agent) => !agent.shares) ?? [],
    has,
  ).filter((agent) => agent.name.toLowerCase().includes(looked));
  const sharedShown =
    "universal".includes(looked) ||
    sharing.some((agent) => agent.name.toLowerCase().includes(looked));
  const linking = chosen.size > 0;
  const named = sharing.slice(0, SHOWN_SHARING).map((agent) => agent.name);

  return (
    <Dialog open onOpenChange={(open) => !open && !working && onClose()}>
      <DialogContent title="Agent Skill" className="sm:max-w-120">
        <div className="flex flex-col gap-3 overflow-y-auto px-5 py-4">
          <p className="text-ink-muted">
            Teaches your agents to create and edit 3D models with this tool. It
            goes in your user folder, so it works in every project.
          </p>
          {listed === null && notListed === null && (
            <p role="status" className="flex items-center gap-2 text-ink-muted">
              <LoadingMark />
              {long
                ? "Finding your agents. The first time, this gets the skills CLI, and Node.js too when it isn't installed."
                : "Finding your agents..."}
            </p>
          )}
          {notListed !== null && (
            <Notice>
              <p>{notListed}</p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={tryAgain}
              >
                Try again
              </Button>
            </Notice>
          )}
          {listed !== null && (
            <>
              <div className="flex flex-col overflow-hidden rounded-md border border-line">
                <input
                  type="text"
                  value={filter}
                  placeholder="Filter agents"
                  aria-label="Filter agents"
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setFilter(event.target.value)}
                  className="h-8 border-b border-line bg-field px-2.5 text-label text-ink outline-none placeholder:text-ink-faint focus-visible:bg-panel"
                />
                <div
                  role="group"
                  aria-label="Agents"
                  className="h-49 overflow-y-auto p-1"
                >
                  {sharedShown && (
                    <AgentRow
                      name="Universal"
                      folder={shortFolder(listed.shared, listed.home)}
                      tag="Always"
                      checked
                      locked
                      also={sharedBy(named, sharing.length - named.length)}
                    />
                  )}
                  {looked === "" && (
                    <div className="mx-2 my-1 border-t border-line" />
                  )}
                  {own.map((agent) => (
                    <AgentRow
                      key={agent.id}
                      name={agent.name}
                      folder={shortFolder(agent.folder, listed.home)}
                      tag={
                        has.has(agent.id)
                          ? "Installed"
                          : agent.detected
                            ? "Found"
                            : null
                      }
                      checked={chosen.has(agent.id)}
                      onChange={(on) => toggle(agent.id, on)}
                    />
                  ))}
                  {!sharedShown && own.length === 0 && (
                    <p className="p-2 text-ink-muted">
                      No agent has that name.
                    </p>
                  )}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-label">Method</p>
                <Segmented
                  label="Method"
                  size="md"
                  full
                  value={mode}
                  onChange={setMode}
                  options={[
                    {
                      value: "symlink",
                      label: "Symlink (Recommended)",
                      disabled: linking ? undefined : NOTHING_TO_LINK,
                    },
                    {
                      value: "copy",
                      label: "Copy",
                      disabled: linking ? undefined : NOTHING_TO_LINK,
                    },
                  ]}
                />
                <p className="mt-1.5 text-caption text-ink-muted">
                  {!linking
                    ? NOTHING_TO_LINK
                    : mode === "symlink"
                      ? "One copy in the shared folder, which each agent's own folder links to."
                      : "A copy of its own in each agent's folder."}
                </p>
              </div>
            </>
          )}
          {problem && <Notice>{problem}</Notice>}
        </div>
        <DialogFooter>
          {installed && (
            <Button
              variant="danger"
              disabled={working}
              onClick={() => finish(dropSkill())}
            >
              Remove
            </Button>
          )}
          <span className="flex-1" />
          {working && <LoadingMark />}
          <Button variant="secondary" onClick={onClose} disabled={working}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={working || listed === null}
            onClick={() => finish(setSkill([...chosen], mode))}
          >
            {installed ? "Save" : "Install"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
