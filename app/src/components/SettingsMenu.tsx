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
  listAgentProviders,
  openAppFolder,
  readAppFolders,
  type AgentProviderStatus,
  type AppFolders,
  type AppSettings,
} from "@/lib/api";
import { APP_NAME, DOCUMENTATION, VERSION } from "@/lib/brand";
import { describe } from "@/lib/errors";
import { app } from "@/lib/host";
import { providerLabel } from "@/lib/intelligence";
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

/** Where the person's settings, this workspace, and its models are kept, read each time Settings opens. */
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

  const open = (folder: "settings" | "workspace" | "models") => {
    setError(null);
    openAppFolder(folder).catch((cause: unknown) => setError(describe(cause)));
  };

  return (
    <Section label="Kept in">
      <FolderRow
        name="Your settings"
        detail="These settings and the workspaces you opened, the same in every workspace"
        path={folders?.settings}
        onOpen={() => open("settings")}
      />
      {folders?.workspace !== null && (
        <>
          <FolderRow
            name="This workspace"
            detail="Your project, where its models' agents work"
            path={folders?.workspace ?? undefined}
            onOpen={() => open("workspace")}
          />
          <FolderRow
            name="Its models"
            detail="Their runs, and what you pinned, last picked, and viewed here"
            path={folders?.models ?? undefined}
            onOpen={() => open("models")}
          />
        </>
      )}
      {error && <Notice className="mt-1">{error}</Notice>}
    </Section>
  );
}

/** How an agent provider stands, for the person. */
function standing(provider: AgentProviderStatus): string {
  if (provider.signed_in) {
    return `Signed in with ${provider.signed_in_with}`;
  }
  return provider.installed ? "Not signed in" : "Not installed";
}

/**
 * The agents the app's runs can use and how each is signed in, with the docs on signing in for one that is not, read
 * each time Settings opens.
 */
function Agents() {
  const [providers, setProviders] = useState<AgentProviderStatus[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const documentation = DOCUMENTATION;

  useEffect(() => {
    let current = true;
    listAgentProviders().then(
      (listed) => current && setProviders(listed),
      (cause: unknown) =>
        current && setError(`Could not check the agents. ${describe(cause)}`),
    );
    return () => {
      current = false;
    };
  }, []);

  return (
    <Section label="Agents">
      {providers === null && !error && (
        <p className="text-caption text-ink-muted">Checking...</p>
      )}
      <div className="flex flex-col gap-1.5">
        {providers?.map((provider) => (
          <div
            key={provider.agent_provider}
            className="flex min-h-8 items-center gap-2"
          >
            <span className="min-w-0 flex-1">
              <span className="block">
                {providerLabel(provider.agent_provider)}
              </span>
              <span
                className="block truncate text-caption text-ink-muted"
                title={provider.problem ?? undefined}
              >
                {standing(provider)}
              </span>
            </span>
            {provider.installed && !provider.signed_in && documentation && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void app.openLink({ url: documentation })}
              >
                How to sign in
                <Icon name="link-out" className="text-ink-muted" />
              </Button>
            )}
          </div>
        ))}
      </div>
      {error && <Notice className="mt-1">{error}</Notice>}
    </Section>
  );
}

/** What is about the app itself: its theme, its agents, where it keeps things, its keys, its layout, and its docs. */
export function SettingsMenu({ onShortcuts }: { onShortcuts?: () => void }) {
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
        <Agents />
        <Folders />
        {error && <Notice className="mx-1 mb-1">{error}</Notice>}
        <hr className="-mx-1 my-1 border-line" />
        {onShortcuts && (
          <>
            <PopoverClose className={ROW} onClick={onShortcuts}>
              <span className="flex-1">Keyboard shortcuts</span>
              <Kbd>?</Kbd>
            </PopoverClose>
            <button type="button" className={ROW} onClick={resetLayout}>
              Reset layout
            </button>
          </>
        )}
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
