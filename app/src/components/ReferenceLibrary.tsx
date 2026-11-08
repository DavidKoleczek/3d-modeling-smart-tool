import { useState, type ReactNode } from "react";

import { ModelThumb } from "@/components/ModelThumb";
import { Button } from "@/components/ui/button";
import { Help } from "@/components/ui/field";
import { Icon, type IconName } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { GROUP_LABEL } from "@/components/ui/popup";
import {
  chooseReferenceFiles,
  chooseReferenceFolder,
  listReferenceFolder,
  stageReferenceFiles,
  type ModelSummary,
  type PinnedFolder,
  type ReferenceEntry,
  type StagedReference,
} from "@/lib/api";
import { describe } from "@/lib/errors";
import {
  baseName,
  entryItem,
  modelItem,
  pinFolder,
  pinnedItems,
  pinnedKeys,
  refreshLibrary,
  togglePin,
  unpinFolder,
  useLibrary,
  useThumbnail,
  type LibraryItem,
} from "@/lib/library";
import { referable, sourceOf, type References } from "@/lib/references";
import { cn } from "@/lib/utils";

type Source = "pinned" | "models" | "used" | `folder:${string}`;

function iconOf(item: LibraryItem): IconName {
  return item.kind === "model" ? "model" : item.kind;
}

function RailItem({
  icon,
  label,
  count,
  active,
  title,
  busy = false,
  onClick,
  actions,
}: {
  icon: IconName;
  label: string;
  count?: number;
  active?: boolean;
  title?: string;
  /** Working on what a click asked for, which shows in place of the count and actions. */
  busy?: boolean;
  onClick: () => void;
  actions?: ReactNode;
}) {
  const acts = !busy && actions;
  return (
    <li className="group/rail relative">
      <button
        type="button"
        onClick={onClick}
        aria-current={active ? "true" : undefined}
        title={title ?? label}
        className={cn(
          "flex h-7 w-full min-w-0 items-center gap-2 rounded-sm pr-1.5 pl-2 text-left text-label -outline-offset-2",
          active ? "bg-accent-soft text-ink" : "text-ink hover:bg-hover",
          acts && "group-focus-within/rail:pr-8 group-hover/rail:pr-8",
        )}
      >
        <Icon name={icon} className="text-ink-muted" />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {busy && <LoadingMark />}
        {!busy && count !== undefined && (
          <span className="mono-annotation text-ink-muted group-focus-within/rail:hidden group-hover/rail:hidden">
            {count}
          </span>
        )}
      </button>
      {acts && (
        <div className="absolute top-1/2 right-0.5 flex -translate-y-1/2 opacity-0 group-focus-within/rail:opacity-100 group-hover/rail:opacity-100">
          {actions}
        </div>
      )}
    </li>
  );
}

function Tile({
  item,
  model,
  picked,
  pinned,
  loading,
  onToggle,
  onPin,
}: {
  item: LibraryItem;
  model: ModelSummary | undefined;
  picked: boolean;
  pinned: boolean;
  loading: boolean;
  onToggle: () => void;
  onPin: () => void;
}) {
  const thumbnail = useThumbnail(item.kind === "file" ? item.path : null);
  return (
    <li className="group/tile relative min-w-0">
      <button
        type="button"
        aria-pressed={picked}
        onClick={onToggle}
        title={
          picked
            ? `${item.name}, picked; click to leave it out`
            : `Work from ${item.kind === "model" ? item.name : item.path}`
        }
        className={cn(
          "relative block aspect-square w-full overflow-hidden rounded-sm border bg-field transition-colors",
          picked
            ? "border-accent-ink ring-1 ring-accent-ink"
            : "border-line hover:border-ink-muted",
        )}
      >
        {model ? (
          <ModelThumb model={model} size="fill" />
        ) : thumbnail ? (
          <img src={thumbnail} alt="" className="size-full object-cover" />
        ) : (
          <span className="grid size-full place-items-center text-ink-muted">
            <Icon name={iconOf(item)} size={24} />
          </span>
        )}
        {picked && (
          <span className="absolute right-1 bottom-1 grid size-4.5 place-items-center rounded-full bg-accent text-on-accent">
            <Icon name="check" />
          </span>
        )}
        {loading && (
          <span className="absolute inset-0 grid place-items-center bg-canvas/60">
            <LoadingMark size={12} />
          </span>
        )}
      </button>
      <button
        type="button"
        aria-pressed={pinned}
        aria-label={pinned ? `Unpin ${item.name}` : `Pin ${item.name}`}
        title={pinned ? "Unpin" : "Pin, to find it in Pinned"}
        onClick={onPin}
        className={cn(
          "shadow-sm absolute top-1 right-1 grid size-6 place-items-center rounded-sm bg-panel/90 hover:text-ink",
          pinned
            ? "text-accent-ink"
            : "text-ink-muted opacity-0 group-focus-within/tile:opacity-100 group-hover/tile:opacity-100",
        )}
      >
        <Icon name={pinned ? "pinned" : "pin"} />
      </button>
      <p
        title={item.name}
        className="mt-1 flex min-w-0 items-center gap-1 mono-annotation text-ink-muted"
      >
        {item.kind === "model" && <Icon name="model" />}
        <span className="truncate">{item.name}</span>
      </p>
    </li>
  );
}

/**
 * What a request can work from, to pick with a click: what the person pinned, the models here, what was chosen or
 * given to the models here before, and pinned folders, each showing what is in it or opening the file dialog there.
 * Other files and folders come in by the file dialogs under them, or dropped or pasted onto whatever holds it.
 */
export function ReferenceLibrary({
  references,
  models,
  exclude,
  compact = false,
}: {
  references: References;
  models: ModelSummary[];
  /** The model the request is on, which is not offered to work from. */
  exclude?: string;
  compact?: boolean;
}) {
  const { library, error } = useLibrary();
  const [source, setSource] = useState<Source>("pinned");
  const [query, setQuery] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState<string[]>([]);
  const [choosing, setChoosing] = useState<string | null>(null);
  // By pinned folder, what was in it when it was last opened.
  const [contents, setContents] = useState<Record<string, ReferenceEntry[]>>(
    {},
  );

  const byName = new Map(models.map((model) => [model.name, model]));
  const pinned = pinnedKeys(library, models);
  const picked = new Map(
    references.items.map((reference) => [sourceOf(reference), reference]),
  );
  const offered = (item: LibraryItem) =>
    !(item.kind === "model" && item.name === exclude);
  const pins = pinnedItems(library, models).filter(offered);
  const modelItems = referable(models)
    .map((model) => modelItem(model.name))
    .filter(offered);
  const used = library.used.map(entryItem);
  const folder = library.folders.find(
    (entry) => source === `folder:${entry.path}`,
  );
  const showing: Source =
    folder || !source.startsWith("folder:") ? source : "pinned";
  const items =
    showing === "pinned"
      ? pins
      : showing === "models"
        ? modelItems
        : showing === "used"
          ? used
          : (contents[folder?.path ?? ""] ?? []).map(entryItem);
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? items.filter((item) => item.name.toLowerCase().includes(needle))
    : items;

  /** Run `work` with `id` showing as busy, adding what it staged, then reading the library for what it remembered. */
  const busy = (id: string, work: () => Promise<StagedReference[] | void>) => {
    if (choosing) {
      return;
    }
    setProblem(null);
    setChoosing(id);
    work()
      .then((staged) => {
        if (staged && staged.length > 0) {
          references.addStaged(staged);
          void refreshLibrary();
        }
      })
      .catch((cause: unknown) => setProblem(describe(cause)))
      .finally(() => setChoosing(null));
  };

  const toggle = (item: LibraryItem) => {
    setProblem(null);
    const reference = picked.get(item.key);
    if (reference) {
      references.remove(reference.key);
      return;
    }
    if (item.kind === "model") {
      references.addModel(item.name);
      return;
    }
    if (loading.includes(item.key)) {
      return;
    }
    setLoading((current) => [...current, item.key]);
    stageReferenceFiles([item.path], true)
      .then((staged) => {
        references.addStaged(staged);
        void refreshLibrary();
      })
      .catch((cause: unknown) => setProblem(describe(cause)))
      .finally(() =>
        setLoading((current) => current.filter((key) => key !== item.key)),
      );
  };

  const openFolder = (entry: PinnedFolder) => {
    setSource(`folder:${entry.path}`);
    setProblem(null);
    listReferenceFolder(entry.path).then(
      (entries) =>
        setContents((current) => ({ ...current, [entry.path]: entries })),
      (cause: unknown) => setProblem(describe(cause)),
    );
  };

  const pinChosenFolder = (shows: PinnedFolder["shows"]) =>
    busy(`pin-${shows}`, async () => {
      const path = await chooseReferenceFolder();
      if (path) {
        pinFolder(path, shows);
      }
    });

  const title =
    showing === "pinned"
      ? "Pinned"
      : showing === "models"
        ? "Models here"
        : showing === "used"
          ? "Used before"
          : baseName(folder?.path ?? "");
  const empty =
    needle && items.length > 0
      ? `Nothing in ${title} matches ${query.trim()}.`
      : showing === "pinned"
        ? "Nothing pinned yet. Pin a reference to keep it here for the next model."
        : showing === "models"
          ? "No model here has a script to work from yet."
          : showing === "used"
            ? "Nothing used here yet. Files chosen to work from show here."
            : `${title} has nothing to work from.`;
  const shownProblem = problem ?? error;

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col",
        compact ? "h-[min(22rem,60dvh)]" : "h-full",
      )}
    >
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Library"
          className={cn(
            "flex shrink-0 flex-col overflow-y-auto border-r border-line p-1",
            compact ? "w-36" : "w-44",
          )}
        >
          <ul className="flex flex-col gap-px">
            <RailItem
              icon="pinned"
              label="Pinned"
              count={pins.length}
              active={showing === "pinned"}
              onClick={() => setSource("pinned")}
            />
            <RailItem
              icon="model"
              label="Models here"
              count={modelItems.length}
              active={showing === "models"}
              onClick={() => setSource("models")}
            />
            <RailItem
              icon="image"
              label="Used before"
              title="What was chosen to work from here, and what the models here were given"
              count={used.length}
              active={showing === "used"}
              onClick={() => setSource("used")}
            />
          </ul>
          <div className="mt-2 flex items-center justify-between">
            <span className={GROUP_LABEL}>Folders</span>
            <Menu>
              <MenuTrigger
                render={
                  <Button
                    size="sm"
                    icon
                    aria-label="Pin a folder"
                    title="Pin a folder"
                  />
                }
              >
                {choosing?.startsWith("pin-") ? (
                  <LoadingMark />
                ) : (
                  <Icon name="add" />
                )}
              </MenuTrigger>
              <MenuContent align="start" className="w-64">
                <MenuItem onClick={() => pinChosenFolder("files")}>
                  <Icon name="folder" className="text-ink-muted" />
                  Folder to browse here...
                </MenuItem>
                <MenuItem onClick={() => pinChosenFolder("dialog")}>
                  <Icon name="file" className="text-ink-muted" />
                  Folder to choose files from...
                </MenuItem>
              </MenuContent>
            </Menu>
          </div>
          <ul className="flex flex-col gap-px">
            {library.folders.map((entry) => {
              const remove = (
                <Button
                  size="sm"
                  icon
                  aria-label={`Unpin ${baseName(entry.path)}`}
                  title="Unpin"
                  onClick={() => unpinFolder(entry.path)}
                >
                  <Icon name="close" />
                </Button>
              );
              return entry.shows === "dialog" ? (
                <RailItem
                  key={entry.path}
                  icon="folder"
                  label={baseName(entry.path)}
                  title={`Choose files from ${entry.path}`}
                  busy={choosing === entry.path}
                  onClick={() =>
                    busy(entry.path, () => chooseReferenceFiles(entry.path))
                  }
                  actions={remove}
                />
              ) : (
                <RailItem
                  key={entry.path}
                  icon="folder"
                  label={baseName(entry.path)}
                  title={entry.path}
                  count={contents[entry.path]?.length}
                  active={showing === `folder:${entry.path}`}
                  onClick={() => openFolder(entry)}
                  actions={remove}
                />
              );
            })}
          </ul>
          <ul className="mt-auto flex flex-col gap-px border-t border-line pt-1">
            <RailItem
              icon="file"
              label="Choose files"
              busy={choosing === "files"}
              onClick={() => busy("files", () => chooseReferenceFiles())}
            />
            <RailItem
              icon="folder"
              label="Choose folder"
              busy={choosing === "folder"}
              onClick={() =>
                busy("folder", async () => {
                  const path = await chooseReferenceFolder();
                  return path ? stageReferenceFiles([path], true) : [];
                })
              }
            />
          </ul>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-9 shrink-0 items-center gap-1.5 border-b border-line pr-1.5 pl-3">
            <span title={folder?.path} className="min-w-0 truncate text-label">
              {title}
            </span>
            <label className="ml-auto flex h-6 w-36 shrink-0 items-center gap-1.5 rounded-sm border border-line-control bg-field pr-1 pl-2 text-ink-muted focus-within:border-ink focus-within:bg-panel">
              <Icon name="search" />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && query) {
                    event.stopPropagation();
                    setQuery("");
                  }
                }}
                placeholder="Filter"
                aria-label={`Filter ${title}`}
                className="min-w-0 flex-1 bg-transparent text-label font-normal text-ink outline-none placeholder:text-ink-muted [&::-webkit-search-cancel-button]:hidden"
              />
            </label>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
            {shownProblem && (
              <Help error className="mt-0 mb-2">
                {shownProblem}
              </Help>
            )}
            {shown.length === 0 ? (
              <p className="px-1 py-6 text-center text-caption text-ink-muted">
                {empty}
              </p>
            ) : (
              <ul
                className={cn(
                  "grid gap-2",
                  compact
                    ? "grid-cols-[repeat(auto-fill,minmax(72px,1fr))]"
                    : "grid-cols-[repeat(auto-fill,minmax(88px,1fr))]",
                )}
              >
                {shown.map((item) => (
                  <Tile
                    key={item.key}
                    item={item}
                    model={
                      item.kind === "model" ? byName.get(item.name) : undefined
                    }
                    picked={picked.has(item.key)}
                    pinned={pinned.has(item.key)}
                    loading={loading.includes(item.key)}
                    onToggle={() => toggle(item)}
                    onPin={() => togglePin(item, models)}
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
