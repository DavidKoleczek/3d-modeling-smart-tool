//! What the exe was started to do, from its arguments.

use std::ffi::OsString;
use std::path::PathBuf;

use crate::failure::{Failure, Outcome};
use crate::install::{Options, Providers};
use crate::paths::SANDBOX_ARGUMENT;
use crate::startup::BACKGROUND;
use crate::update::UPDATE;

const USAGE: &str = "\
Modeling3DSetup.exe
    Open setup. Once installed, the exe opens the app in the browser instead, and stays by the clock.
Modeling3DSetup.exe --background
    Run the app without opening the browser, as Windows does at sign-in.
Modeling3DSetup.exe --install [--workspace <folder>] [--agent-provider claude|codex]... [--desktop-shortcut]
        [--start-menu-shortcut] [--start-at-sign-in]
    Install without asking anything, with uv when it is missing, and both agent providers unless some are named. The
    folder becomes the first workspace when there is none. The Agent Skill is updated where it is installed. Refuses
    while something runs from the tool, and says what.
Modeling3DSetup.exe --update
    Install this exe over the installed app as that one was set up, and start the app again. The app does this with
    a newer exe it has downloaded.
Modeling3DSetup.exe --add-agent-provider claude|codex
    Install the tool again with this agent provider as well as those it has, keep the rest as it was set up, and
    start the app again. The app's settings do this.
Modeling3DSetup.exe --uninstall [--quiet]
    Remove the app and the tool, and keep the workspaces, the models, and the sign-ins. Asks first, unless --quiet.

Any of these takes --sandbox <folder>, which keeps everything it installs and changes in that folder.";

#[derive(Debug, PartialEq)]
pub enum Command {
    /// Opened with nothing said, as a shortcut or a download is: the app when the exe is the installed one, and
    /// setup otherwise.
    Open,
    Background,
    Install(Options),
    /// Install over the app as it was set up, with these agent providers as well as those it has.
    Update(Providers),
    Uninstall {
        quiet: bool,
    },
}

/// What the exe was asked: a command, and the sandbox to do it in.
#[derive(Debug, PartialEq)]
pub struct Invocation {
    pub command: Command,
    pub sandbox: Option<PathBuf>,
}

/// Reads the arguments after the exe's own name.
pub fn parse(arguments: impl IntoIterator<Item = OsString>) -> Outcome<Invocation> {
    let mut alone = Vec::new();
    let mut install = false;
    let mut uninstall = false;
    let mut quiet = false;
    let mut chosen = false;
    let mut sandbox = None;
    // Named ones replace both, which is what there is otherwise.
    let mut named: Option<Providers> = None;
    let mut options = Options::default();
    let mut arguments = arguments.into_iter();
    while let Some(argument) = arguments.next() {
        match argument.to_str() {
            Some(BACKGROUND) => alone.push(Command::Background),
            Some(UPDATE) => alone.push(Command::Update(Providers::NONE)),
            Some("--add-agent-provider") => {
                let name = arguments.next();
                let adding = name.as_ref().and_then(|name| name.to_str()).and_then(Providers::named);
                alone
                    .push(Command::Update(adding.ok_or_else(|| wrong("--add-agent-provider needs claude or codex."))?));
            }
            Some("--install") => install = true,
            Some("--uninstall") => uninstall = true,
            Some("--quiet") => quiet = true,
            Some("--desktop-shortcut") => (chosen, options.shortcuts.desktop) = (true, true),
            Some("--start-menu-shortcut") => (chosen, options.shortcuts.start_menu) = (true, true),
            Some("--start-at-sign-in") => (chosen, options.start_at_sign_in) = (true, true),
            Some("--workspace") => {
                let folder = arguments.next().ok_or_else(|| wrong("--workspace needs a folder."))?;
                (chosen, options.workspace) = (true, Some(PathBuf::from(folder)));
            }
            Some("--agent-provider") => {
                let name = arguments.next();
                let one = name.as_ref().and_then(|name| name.to_str()).and_then(Providers::named);
                let one = one.ok_or_else(|| wrong("--agent-provider needs claude or codex."))?;
                named = Some(named.unwrap_or(Providers::NONE).and(one));
                chosen = true;
            }
            Some(SANDBOX_ARGUMENT) => {
                let folder = arguments.next().ok_or_else(|| wrong("--sandbox needs a folder."))?;
                sandbox = Some(PathBuf::from(folder));
            }
            _ => return Err(wrong(&format!("{} isn't an argument of this exe.", argument.display()))),
        }
    }
    if let Some(providers) = named {
        options.agent_providers = providers;
    }
    let command = match (install, uninstall) {
        _ if alone.len() > 1 || (!alone.is_empty() && (install || uninstall || quiet || chosen)) => {
            Err(wrong("--background, --update, and --add-agent-provider each go alone, or with --sandbox."))
        }
        (true, true) => Err(wrong("--install and --uninstall can't go together.")),
        (true, false) if quiet => Err(wrong("--quiet goes with --uninstall. --install never asks anything.")),
        (true, false) => Ok(Command::Install(options)),
        (false, _) if chosen => Err(wrong("What to install goes with --install.")),
        (false, true) => Ok(Command::Uninstall { quiet }),
        (false, false) if quiet => Err(wrong("--quiet goes with --uninstall.")),
        (false, false) => Ok(alone.pop().unwrap_or(Command::Open)),
    }?;
    Ok(Invocation { command, sandbox })
}

fn wrong(problem: &str) -> Failure {
    Failure::new(format!("{problem}\n\n{USAGE}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::Shortcuts;

    fn parsed(arguments: &[&str]) -> Outcome<Command> {
        parse(arguments.iter().map(OsString::from)).map(|invocation| invocation.command)
    }

    #[test]
    fn no_arguments_open_it() {
        assert_eq!(parsed(&[]).unwrap(), Command::Open);
    }

    #[test]
    fn background_is_what_windows_starts_it_with() {
        assert_eq!(parsed(&["--background"]).unwrap(), Command::Background);
    }

    #[test]
    fn install_takes_what_setup_would_ask() {
        const WORKSPACE: &str = "D:/models";
        let arguments = [
            "--install",
            "--workspace",
            WORKSPACE,
            "--agent-provider",
            "codex",
            "--desktop-shortcut",
            "--start-at-sign-in",
        ];
        let options = Options {
            workspace: Some(PathBuf::from(WORKSPACE)),
            agent_providers: Providers { claude: false, codex: true },
            shortcuts: Shortcuts { desktop: true, start_menu: false },
            start_at_sign_in: true,
            ..Options::default()
        };
        assert_eq!(parsed(&arguments).unwrap(), Command::Install(options));
        assert_eq!(parsed(&["--install"]).unwrap(), Command::Install(Options::default()));
    }

    #[test]
    fn both_agent_providers_are_installed_unless_some_are_named() {
        let providers = |arguments: &[&str]| match parsed(arguments).unwrap() {
            Command::Install(options) => options.agent_providers,
            command => panic!("{command:?}"),
        };
        assert_eq!(providers(&["--install"]), Providers { claude: true, codex: true });
        assert_eq!(providers(&["--install", "--agent-provider", "claude"]), Providers { claude: true, codex: false });
        let both = ["--install", "--agent-provider", "codex", "--agent-provider", "claude"];
        assert_eq!(providers(&both), Providers { claude: true, codex: true });
    }

    #[test]
    fn an_update_installs_over_the_app_with_any_agent_provider_added() {
        assert_eq!(parsed(&["--update"]).unwrap(), Command::Update(Providers::NONE));
        let codex = Providers { claude: false, codex: true };
        assert_eq!(parsed(&["--add-agent-provider", "codex"]).unwrap(), Command::Update(codex));
    }

    #[test]
    fn uninstall_asks_unless_quiet() {
        assert_eq!(parsed(&["--uninstall"]).unwrap(), Command::Uninstall { quiet: false });
        assert_eq!(parsed(&["--uninstall", "--quiet"]).unwrap(), Command::Uninstall { quiet: true });
    }

    #[test]
    fn a_sandbox_goes_with_any_command() {
        let invocation = |arguments: &[&str]| parse(arguments.iter().map(OsString::from)).unwrap();
        let sandboxed = invocation(&["--sandbox", r"D:\try", "--background"]);
        assert_eq!(sandboxed, Invocation { command: Command::Background, sandbox: Some(PathBuf::from(r"D:\try")) });
        assert_eq!(invocation(&["--uninstall", "--sandbox", "try"]).sandbox, Some(PathBuf::from("try")));
        assert_eq!(invocation(&[]).sandbox, None);
    }

    #[test]
    fn arguments_that_dont_go_together_are_refused_with_the_usage() {
        for arguments in [
            &["--install", "--uninstall"][..],
            &["--install", "--quiet"],
            &["--uninstall", "--desktop-shortcut"],
            &["--workspace", r"D:\models"],
            &["--install", "--workspace"],
            &["--install", "--agent-provider"],
            &["--install", "--agent-provider", "copilot"],
            &["--sandbox"],
            &["--quiet"],
            &["--background", "--install"],
            &["--background", "--quiet"],
            &["--background", "--background"],
            &["--update", "--install"],
            &["--update", "--add-agent-provider", "codex"],
            &["--add-agent-provider"],
            &["--add-agent-provider", "copilot"],
            &["--add-agent-provider", "claude", "--desktop-shortcut"],
            &["--unknown"],
        ] {
            let failure = parsed(arguments).unwrap_err().to_string();
            assert!(failure.contains("--install [--workspace <folder>]"), "{arguments:?}: {failure}");
        }
    }
}
