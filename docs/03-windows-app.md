# Windows App

`Modeling3DSetup.exe` installs the tool on Windows and adds an app for it: a shortcut that serves the [app](01-library.md#app), opens it in the browser, and stays in the tray.

Everything is installed for the current user only, so Windows doesn't ask for an administrator.

## Install

Download [Modeling3DSetup.exe](https://github.com/DavidKoleczek/3d-modeling-smart-tool/releases/latest/download/Modeling3DSetup.exe) and open it. The exe isn't signed, so Windows warns about it first: choose More info, then Run anyway.

Setup asks a few things:

- First workspace: the folder your models are made in, `Documents\3D Models` to begin with. Browse picks one that is there already. Leave it empty to pick one in the app. It isn't asked when the app has workspaces from before, which uninstalling keeps.
- Agent providers: Claude, Codex, or both, which are both on to begin with. Each comes with its own runtime, so Claude Code and the Codex CLI don't need to be installed. The other can be installed later from the app's settings.
- Desktop shortcut and Start menu shortcut: on to begin with.
- Start when I sign in: off to begin with.
- Agent Skill: on to begin with. Next, it lists the agents the [skills CLI](https://github.com/vercel-labs/skills) knows, with the ones on this computer ticked. The skill goes in `~\.agents\skills`, which many agents read, and each agent ticked that has a folder of its own gets a link to it there, or a copy.

Then it installs:

1. uv, when it is missing, with [Astral's install script](https://docs.astral.sh/uv/getting-started/installation/), which puts it on your `PATH`.
1. The tool, with `uv tool install` and the agent providers chosen. `modeling-3d` is on `PATH` as it is when installed by hand, and a tool that was installed by hand is replaced.
1. The first workspace, the Agent Skill, the shortcuts, and the entry in Windows' installed apps.

Last, it shows whether each agent provider is signed in. How to sign in opens the [Quickstart](../README.md#quickstart), and Check again looks once you have. Both providers keep their sign-ins in your user folder, so if you are signed in to Claude Code or Codex already, you are signed in here too.

The skill is the one that comes with this version of the tool. The skills CLI installs it, run on the Node that is installed when it is new enough. Otherwise Node is downloaded from nodejs.org, checked against the SHA-256 the exe was built with, and deleted once the skill is in.

Opening the exe again shows what is installed, and installs again with whatever is chosen then.

## While the tool is in use

The tool can't be replaced or removed while something runs from it: a run building a model, an agent session's `modeling-3d mcp`, or a command in a terminal. So setup and updates look first, and say what they found. Wait goes on by itself once they end. Stop them and continue ends them; a run that is stopped can be resumed later. Back leaves everything as it was. Uninstall asks whether to stop them.

## The app

Opening 3D Modeling serves the app in the background, opens it in the browser, and puts its icon in the tray. Opening it again only opens the browser. Closing the browser tab doesn't stop it.

It is served at `http://127.0.0.1:8788`. When something else holds that port, a free one is used and remembered. The first time, it opens on the workspace setup made, and after that on the one opened last, as `modeling-3d app` does.

Clicking the icon opens the app in the browser. Its menu has:

- Open
- Start when I sign in: starts it with Windows, without opening the browser.
- Check for updates
- Quit: stops serving the app. Runs started from it go on.

The app's settings menu also has the version and the update, Start when I sign in, the agents the skill is installed for, and Install beside an agent provider that isn't installed. These show only when the app was started from the tray. Installing a provider opens a window that installs it and starts the app again, and the page loads again by itself once the app is back.

## Updates

The app asks GitHub for the newest release when it starts and once a day, and sends nothing but its own name and version. When there is a newer one, nothing pops up. The tray icon gets a dot, and the tray's menu and the app's settings offer the update.

Update downloads the new `Modeling3DSetup.exe`, checks it against the SHA-256 GitHub publishes for it, and runs it. That installs over the app as it was set up, updates the tool and the skill, and starts the app again.

The tool's version comes with the app, so `uv tool upgrade` finds nothing to upgrade.

## What it installs

Files:

- `%LOCALAPPDATA%\Programs\3D Modeling\Modeling3D.exe`: the app, which is the same exe as setup.
- `%LOCALAPPDATA%\3D Modeling`: the tool's wheel, downloaded updates, the setup window's browser data, and where the skill went.
- `%APPDATA%\modeling-3d\windows-app.json`: the app's port, beside the tool's own settings and workspaces.
- The shortcuts, on the desktop and in the Start menu.
- The tool, where uv keeps its tools. uv fetches Python for it when it has none that fits.
- The Agent Skill, in `~\.agents\skills\modeling-3d`, and linked or copied into the folders of the agents chosen.

Registry, all under `HKEY_CURRENT_USER`:

- The key `Software\Microsoft\Windows\CurrentVersion\Uninstall\Modeling3D`, which lists it in Windows' installed apps.
- The value `Modeling3D` in `Software\Microsoft\Windows\CurrentVersion\Run`, only while Start when I sign in is on.

uv adds its folders to your `PATH`.

## Uninstall

Uninstall 3D Modeling from Windows' installed apps. That removes the app, the tool, the Agent Skill, the shortcuts, and the registry entries.

It keeps your workspaces and their models, everything in `%APPDATA%\modeling-3d` and `%LOCALAPPDATA%\modeling-3d`, the agent providers' sign-ins, and uv with its Python. uv stays on your `PATH`.

## Without the window

```
Modeling3DSetup.exe --install [--workspace <folder>] [--agent-provider claude|codex]... [--desktop-shortcut]
                              [--start-menu-shortcut] [--start-at-sign-in]
Modeling3DSetup.exe --uninstall [--quiet]
```

`--install` asks nothing and installs with what the options name, so a shortcut that isn't named isn't made. Both agent providers are installed unless `--agent-provider` names some. `--workspace` names the first workspace, used only when the app has none yet. The Agent Skill is updated where it is installed, and isn't installed otherwise. It prints whether each provider is signed in. `--uninstall` asks first, unless `--quiet`. With nobody to ask, `--install` and `--uninstall --quiet` refuse while the tool is in use, and list what runs from it.

In PowerShell, add `| Out-Host` to wait for the exe and see what it prints.
