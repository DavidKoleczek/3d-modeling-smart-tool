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
import { Switch } from "@/components/ui/switch";
import { Tooltip } from "@/components/ui/tooltip";
import { SkillDialog } from "@/components/SkillDialog";
import {
  listAgentProviders,
  openAppFolder,
  readAppFolders,
  type AgentProviderStatus,
  type AppFolders,
  type AppSettings,
  type WindowsApp,
} from "@/lib/api";
import { APP_NAME, DOCUMENTATION, VERSION } from "@/lib/brand";
import { AppError, describe } from "@/lib/errors";
import { app } from "@/lib/host";
import { providerLabel } from "@/lib/intelligence";
import { resetLayout, updateSettings, useSettings } from "@/lib/settings";
import {
  addAgentProvider,
  lookForUpdate,
  refreshWindowsApp,
  setStartAtSignIn,
  update,
  useWindowsApp,
} from "@/lib/windowsApp";

// A host that serves no version still gets the app's name there.
const VERSION_LABEL = VERSION ? `${APP_NAME} ${VERSION}` : APP_NAME;
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

/**
 * The folder of the settings that are the same in every workspace, read each time Settings opens, which opens in the
 * person's file manager.
 */
function GlobalSettings() {
  const [folders, setFolders] = useState<AppFolders | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = folders?.settings;

  useEffect(() => {
    let current = true;
    readAppFolders().then(
      (read) => current && setFolders(read),
      (cause: unknown) =>
        current &&
        setError(
          `Could not read where the global settings are. ${describe(cause)}`,
        ),
    );
    return () => {
      current = false;
    };
  }, []);

  const open = () => {
    setError(null);
    openAppFolder("settings").catch((cause: unknown) =>
      setError(describe(cause)),
    );
  };

  return (
    <div className="px-2 py-1.5">
      <button
        type="button"
        disabled={!path}
        onClick={open}
        title={path && `Open ${path}`}
        className="-mx-1 flex w-[calc(100%+0.5rem)] cursor-default items-start gap-2 rounded-sm p-1 text-left hover:bg-hover disabled:hover:bg-transparent"
      >
        <Icon name="folder" className="mt-0.5 text-ink-muted" />
        <span className="min-w-0 flex-1">
          <span className="block">Global settings</span>
          <span className="mt-0.5 block mono-annotation break-all text-ink-muted">
            {path ?? "..."}
          </span>
        </span>
        <Icon name="link-out" className="mt-0.5 text-ink-muted" />
      </button>
      {error && <Notice className="mt-1">{error}</Notice>}
    </div>
  );
}

/**
 * What the Windows app said it couldn't do. A call that got no answer at all isn't one of these: the server it went
 * through has ended, which is what installing an update or an agent provider asks for.
 */
function refusal(cause: unknown): string | null {
  return cause instanceof AppError ? describe(cause) : null;
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
function Agents({ windowsApp }: { windowsApp: WindowsApp | null }) {
  const [providers, setProviders] = useState<AgentProviderStatus[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  // The agent provider the Windows app is installing, which ends this server and starts it again once done.
  const [installing, setInstalling] = useState<string | null>(null);
  const documentation = DOCUMENTATION;

  const install = (agentProvider: string) => {
    setError(null);
    setInstalling(agentProvider);
    addAgentProvider(agentProvider).catch((cause: unknown) => {
      const refused = refusal(cause);
      if (refused !== null) {
        setInstalling(null);
        setError(refused);
      }
    });
  };

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
            {!provider.installed && windowsApp && (
              <Button
                size="sm"
                variant="secondary"
                disabled={installing !== null}
                title={`Install the tool again with ${providerLabel(provider.agent_provider)}`}
                onClick={() => install(provider.agent_provider)}
              >
                Install
              </Button>
            )}
          </div>
        ))}
      </div>
      {installing && (
        <p role="status" className="mt-1 text-caption text-ink-muted">
          Installing {providerLabel(installing)}. {APP_NAME} closes, and this
          page loads again once it is back.
        </p>
      )}
      {error && <Notice className="mt-1">{error}</Notice>}
    </Section>
  );
}

/** What the Windows app keeps, since it is about how the app starts, and its Agent Skill. */
function ThisComputer({
  windowsApp,
  onChooseSkill,
}: {
  windowsApp: WindowsApp;
  onChooseSkill: () => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const skill = windowsApp.skill;

  const changeStartAtSignIn = (on: boolean) => {
    setProblem(null);
    setStartAtSignIn(on).catch((cause: unknown) => setProblem(describe(cause)));
  };

  return (
    <Section label="This computer">
      <Switch
        className="flex h-7"
        checked={windowsApp.start_at_sign_in}
        onChange={changeStartAtSignIn}
      >
        Start when I sign in
      </Switch>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-label">Agent Skill</p>
          <p className="text-caption text-ink-muted">
            {skill
              ? skillFor(skill.agents)
              : "Teaches your agents to create and edit 3D models."}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={onChooseSkill}>
          {skill ? "Change" : "Install"}
        </Button>
      </div>
      {problem && <Notice className="mt-1.5">{problem}</Notice>}
    </Section>
  );
}

/** Who the Agent Skill is installed for, as the skills CLI names them. */
function skillFor(names: string[]): string {
  if (names.length === 0) {
    return "In the shared folder only";
  }
  return names.length > 2
    ? `For ${names[0]}, ${names[1]}, and ${names.length - 2} more`
    : `For ${names.join(" and ")}`;
}

/** This version, with the newer one the Windows app has found, or a look for one. */
function Update({ windowsApp }: { windowsApp: WindowsApp }) {
  const [checking, setChecking] = useState(false);
  const [looked, setLooked] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const check = () => {
    setProblem(null);
    setChecking(true);
    lookForUpdate()
      .then(() => setLooked(true))
      .catch((cause: unknown) => setProblem(describe(cause)))
      .finally(() => setChecking(false));
  };
  const install = () => {
    setProblem(null);
    update().catch((cause: unknown) => setProblem(refusal(cause)));
  };

  const version = windowsApp.update;
  return (
    <div className="px-2 pb-1">
      <div className="flex h-6 items-center gap-2">
        <p className="flex-1 mono-annotation text-ink-muted">{VERSION_LABEL}</p>
        {version === null && (
          <Button
            variant="secondary"
            size="sm"
            disabled={checking}
            onClick={check}
          >
            {checking ? "Checking..." : "Check for updates"}
          </Button>
        )}
      </div>
      {version === null ? (
        looked &&
        !checking && (
          <p
            role="status"
            className="mt-1 text-right text-caption text-ink-muted"
          >
            This is the newest version.
          </p>
        )
      ) : windowsApp.updating ? (
        <p role="status" className="flex h-6 items-center text-label">
          Updating to {version}...
        </p>
      ) : (
        <div className="mt-1 flex items-center gap-2">
          <span className="size-1.5 shrink-0 rounded-full bg-accent" />
          <p className="flex-1 text-label">Version {version} is available.</p>
          <Button variant="primary" size="sm" onClick={install}>
            Update
          </Button>
        </div>
      )}
      {problem && <Notice className="mt-1.5">{problem}</Notice>}
    </div>
  );
}

/** What is about the app itself: its theme, its agents, its global settings' folder, its keys, its layout, and its docs. */
export function SettingsMenu({ onShortcuts }: { onShortcuts?: () => void }) {
  const { settings, error } = useSettings();
  const documentation = DOCUMENTATION;
  const set = (change: Partial<AppSettings>) =>
    updateSettings((current) => ({ ...current, ...change }));
  // Only when the Windows app is what started the server.
  const windowsApp = useWindowsApp();
  const newer = windowsApp?.update ?? null;
  const title =
    newer === null ? "Settings" : `Settings. Version ${newer} is available.`;
  const [open, setOpen] = useState(false);
  // Outside the menu, which closes as the dialog opens.
  const [choosingSkill, setChoosingSkill] = useState(false);

  return (
    <>
      <Popover
        open={open}
        onOpenChange={(opening) => {
          setOpen(opening);
          // It changes from its own menu too.
          if (opening && windowsApp) {
            void refreshWindowsApp();
          }
        }}
      >
        <Tooltip content={title}>
          <PopoverTrigger
            render={
              <Button size="sm" icon aria-label={title} className="relative" />
            }
          >
            <Icon name="sliders" />
            {newer !== null && (
              <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-accent" />
            )}
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
          <Agents windowsApp={windowsApp} />
          {windowsApp && (
            <ThisComputer
              windowsApp={windowsApp}
              onChooseSkill={() => {
                setOpen(false);
                setChoosingSkill(true);
              }}
            />
          )}
          <GlobalSettings />
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
          {windowsApp ? (
            <Update windowsApp={windowsApp} />
          ) : (
            <p className="flex h-6 items-center px-2 mono-annotation text-ink-muted">
              {VERSION_LABEL}
            </p>
          )}
        </PopoverContent>
      </Popover>
      {choosingSkill && windowsApp && (
        <SkillDialog
          installed={windowsApp.skill !== null}
          installedMode={windowsApp.skill?.mode ?? "symlink"}
          onClose={() => setChoosingSkill(false)}
        />
      )}
    </>
  );
}
