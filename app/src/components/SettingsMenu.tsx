import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Kbd } from "@/components/ui/kbd";
import { Notice } from "@/components/ui/notice";
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import {
  openAppFolder,
  readAppFolders,
  type AppFolders,
  type AppSettings,
} from "@/lib/api";
import { APP_NAME, DOCUMENTATION, VERSION } from "@/lib/brand";
import { describe } from "@/lib/errors";
import { app } from "@/lib/host";
import { resetLayout, updateSettings, useSettings } from "@/lib/settings";

const ROW =
  "flex h-7 w-full cursor-default items-center gap-2 rounded-sm px-2 text-left whitespace-nowrap hover:bg-hover";

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="px-2 pt-2 pb-2.5">
      <p className="mb-1.5 text-label text-ink-muted">{label}</p>
      {children}
    </div>
  );
}

/** A folder the app keeps something in, which opens in the person's file manager. */
function FolderRow({
  name,
  detail,
  path,
  onOpen,
}: {
  name: string;
  detail: string;
  path: string | undefined;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      disabled={!path}
      onClick={onOpen}
      title={path && `Open ${path}`}
      className="-mx-1 flex w-[calc(100%+0.5rem)] cursor-default items-start gap-2 rounded-sm p-1 text-left hover:bg-hover disabled:hover:bg-transparent"
    >
      <Icon name="folder" className="mt-0.5 text-ink-muted" />
      <span className="min-w-0 flex-1">
        <span className="block">{name}</span>
        <span className="block text-caption text-ink-muted">{detail}</span>
        <span className="mt-0.5 block mono-annotation break-all text-ink-muted">
          {path ?? "..."}
        </span>
      </span>
      <Icon name="link-out" className="mt-0.5 text-ink-muted" />
    </button>
  );
}

/** Where the person's settings and this directory's models are kept, read each time Settings opens. */
function Folders() {
  const [folders, setFolders] = useState<AppFolders | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    readAppFolders().then(
      (read) => current && setFolders(read),
      (cause: unknown) =>
        current &&
        setError(`Could not read where things are kept. ${describe(cause)}`),
    );
    return () => {
      current = false;
    };
  }, []);

  const open = (folder: "settings" | "models") => {
    setError(null);
    openAppFolder(folder).catch((cause: unknown) => setError(describe(cause)));
  };

  return (
    <Section label="Kept in">
      <FolderRow
        name="Your settings"
        detail="These settings, the same in every directory"
        path={folders?.settings}
        onOpen={() => open("settings")}
      />
      <FolderRow
        name="This directory"
        detail="Its models, their runs, and what you last picked and viewed here"
        path={folders?.models}
        onOpen={() => open("models")}
      />
      {error && <Notice className="mt-1">{error}</Notice>}
    </Section>
  );
}

/** What is about the app itself: its theme, where it keeps things, its keys, its layout, and its docs. */
export function SettingsMenu({ onShortcuts }: { onShortcuts: () => void }) {
  const { settings, error } = useSettings();
  const documentation = DOCUMENTATION;
  const set = (change: Partial<AppSettings>) =>
    updateSettings((current) => ({ ...current, ...change }));

  return (
    <Popover>
      <Tooltip content="Settings">
        <PopoverTrigger
          render={<Button size="sm" icon aria-label="Settings" />}
        >
          <Icon name="sliders" />
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent label="Settings" className="w-75">
        <Section label="Theme">
          <Segmented
            label="Theme"
            size="sm"
            full
            value={settings.theme}
            onChange={(theme) => set({ theme })}
            options={[
              { value: "system", label: "System", icon: "monitor" },
              { value: "light", label: "Light", icon: "sun" },
              { value: "dark", label: "Dark", icon: "moon" },
            ]}
          />
        </Section>
        <Folders />
        {error && <Notice className="mx-1 mb-1">{error}</Notice>}
        <hr className="-mx-1 my-1 border-line" />
        <PopoverClose className={ROW} onClick={onShortcuts}>
          <span className="flex-1">Keyboard shortcuts</span>
          <Kbd>?</Kbd>
        </PopoverClose>
        <button type="button" className={ROW} onClick={resetLayout}>
          Reset layout
        </button>
        {documentation && (
          <button
            type="button"
            className={ROW}
            onClick={() => void app.openLink({ url: documentation })}
          >
            <span className="flex-1">Documentation</span>
            <Icon name="link-out" className="text-ink-muted" />
          </button>
        )}
        <hr className="-mx-1 my-1 border-line" />
        <p className="flex h-6 items-center px-2 mono-annotation text-ink-muted">
          {APP_NAME}
          {VERSION && ` ${VERSION}`}
        </p>
      </PopoverContent>
    </Popover>
  );
}
