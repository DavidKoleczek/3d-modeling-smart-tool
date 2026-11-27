//! Installing the app and the tool for the current user, and removing them.

use std::os::windows::process::CommandExt;
use std::path::{self, Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use std::{env, fs, io, thread};

use windows::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_registry::CURRENT_USER;

use crate::failure::{Failure, OrSay, Outcome};
use crate::in_use::InUse;
use crate::package::{APP_NAME, PUBLISHER, REPOSITORY, VERSION};
use crate::paths::Paths;
use crate::settings::Settings;
use crate::skill::{self, Choice, Kit, Mode, Record};
use crate::{instance, prerequisites, startup, tool, win32};

const VERSION_VALUE: &str = "DisplayVersion";
// The folder a first workspace is suggested as, in the user's documents.
const FIRST_WORKSPACE: &str = "3D Models";
// An app that has only just quit can hold its exe a moment longer.
const COPY_PATIENCE: Duration = Duration::from_secs(5);
const COPY_CHECK: Duration = Duration::from_millis(100);
// How often what runs from the tool is looked at again while it is waited for.
const IN_USE_CHECK: Duration = Duration::from_secs(1);

/// What the person installing chose.
#[derive(Debug, Default, PartialEq)]
pub struct Options {
    /// The folder for a first workspace, used only when the app has opened none yet.
    pub workspace: Option<PathBuf>,
    pub agent_providers: Providers,
    pub shortcuts: Shortcuts,
    pub start_at_sign_in: bool,
    pub skill: Choice,
}

/// Which agent providers the tool is installed with, each an extra of its package.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Providers {
    pub claude: bool,
    pub codex: bool,
}

impl Default for Providers {
    fn default() -> Self {
        Self { claude: true, codex: true }
    }
}

impl Providers {
    pub const NONE: Self = Self { claude: false, codex: false };

    /// Returns the one agent provider by this name, as the tool names it.
    pub fn named(name: &str) -> Option<Self> {
        match name {
            "claude" => Some(Self { claude: true, codex: false }),
            "codex" => Some(Self { claude: false, codex: true }),
            _ => None,
        }
    }

    /// Returns these and those, together.
    pub fn and(self, other: Self) -> Self {
        Self { claude: self.claude || other.claude, codex: self.codex || other.codex }
    }

    /// Returns whether every one of `other` is among these.
    pub fn has(self, other: Self) -> bool {
        self.and(other) == self
    }

    /// Returns the extras that install these, as they go between the brackets after a package.
    pub fn extras(self) -> String {
        let named = [(self.claude, "claude"), (self.codex, "codex")];
        named.into_iter().filter(|(wanted, _)| *wanted).map(|(_, name)| name).collect::<Vec<_>>().join(",")
    }
}

/// Which shortcuts to the app there are to be.
#[derive(Debug, Default, PartialEq)]
pub struct Shortcuts {
    pub desktop: bool,
    pub start_menu: bool,
}

/// What is on the machine before anything is installed.
pub struct Existing {
    /// The version of the app that is installed, if one is.
    pub version: Option<String>,
    /// The workspaces opened in the app, newest first.
    pub workspaces: Vec<PathBuf>,
    /// How the Agent Skill was installed, if it is.
    pub skill: Option<Mode>,
    /// The choices that would leave an installed app as it is, or the ones to start from when there is none.
    pub options: Options,
}

/// What to do about what runs from the tool, which has to end before the tool is replaced or removed.
pub enum Clearing {
    /// Look again in a moment.
    Wait,
    Stop,
}

#[derive(Clone, Copy)]
pub enum Stage {
    InstallUv,
    Stop,
    InstallTool,
    MakeWorkspace,
    InstallSkill,
    UpdateSkill,
    RemoveSkill,
    InstallApp,
    RemoveTool,
    RemoveApp,
}

pub enum Progress {
    Started(Stage),
    /// Something that didn't go as asked and didn't stop the rest.
    Note(String),
}

impl Stage {
    pub fn label(self) -> &'static str {
        match self {
            Self::InstallUv => "Installing uv",
            Self::Stop => "Stopping what runs from the tool",
            Self::InstallTool => "Installing the tool",
            Self::MakeWorkspace => "Making the workspace",
            Self::InstallSkill => "Installing the Agent Skill",
            Self::UpdateSkill => "Updating the Agent Skill",
            Self::RemoveSkill => "Removing the Agent Skill",
            Self::InstallApp => "Installing the app and tray icon",
            Self::RemoveTool => "Removing the tool",
            Self::RemoveApp => "Removing the app from Windows",
        }
    }
}

impl Existing {
    /// Looks at what is installed.
    pub fn find(paths: &Paths) -> Self {
        let version = CURRENT_USER.open(paths.uninstall_key()).and_then(|key| key.get_string(VERSION_VALUE)).ok();
        let workspaces = tool::workspaces(paths);
        let installed = version.is_some();
        // The tool may have been installed by hand, or kept from an app that was removed.
        let providers = prerequisites::find_uv(paths)
            .and_then(|uv| tool::files(&uv, paths).ok())
            .and_then(|files| tool::installed_providers(&files))
            .filter(|providers| *providers != Providers::NONE);
        let options = Options {
            workspace: workspaces.is_empty().then(|| paths.documents.join(FIRST_WORKSPACE)),
            agent_providers: providers.unwrap_or_default(),
            shortcuts: Shortcuts {
                desktop: !installed || shortcut(&paths.desktop).is_file(),
                start_menu: !installed || shortcut(&paths.start_menu).is_file(),
            },
            start_at_sign_in: startup::is_on(paths),
            skill: Choice::Keep,
        };
        Self { version, workspaces, skill: Record::read(paths).map(|record| record.mode), options }
    }

    /// Returns the choices that install over the app and leave it as it was set up, which is how it is updated, with
    /// the agent providers in `adding` as well as those it has.
    pub fn kept(self, adding: Providers) -> Outcome<Options> {
        if self.version.is_none() {
            return Err(Failure::new(format!(
                "{APP_NAME} isn't installed, so there is nothing to update. Open this exe by itself to set it up."
            )));
        }
        let agent_providers = self.options.agent_providers.and(adding);
        Ok(Options { workspace: None, agent_providers, ..self.options })
    }
}

/// Installs uv when it is missing, then the tool with the agent providers chosen, its Agent Skill, and the app, in
/// place of any version already there, and returns the tool's program. The skills CLI is gotten ready for the skill
/// unless `kit` is it. `clear` is asked what to do about what runs from the tool, for as long as something does.
///
/// Windows is told of the app last, so an install that fails on the way leaves nothing listed.
pub fn install(
    options: &Options,
    kit: Option<Kit>,
    paths: &Paths,
    report: &mut dyn FnMut(Progress),
    clear: &mut dyn FnMut(&InUse) -> Outcome<Clearing>,
) -> Outcome<PathBuf> {
    if options.agent_providers == Providers::NONE {
        return Err(Failure::new("The tool is installed with claude, codex, or both. Choose at least one."));
    }
    // A running app holds the tool's files and the exe, which are both about to be replaced.
    instance::quit_running(paths)?;
    let uv = if let Some(uv) = prerequisites::find_uv(paths) {
        uv
    } else {
        report(Progress::Started(Stage::InstallUv));
        prerequisites::install_uv(paths)?
    };
    free_the_tool(&uv, paths, report, clear)?;

    report(Progress::Started(Stage::InstallTool));
    let program = tool::install(&uv, options.agent_providers, paths)?;
    // A sandbox's tools are not for the rest of the machine to find.
    if !paths.is_sandbox()
        && let Err(failure) = tool::put_on_path(&uv, paths)
    {
        report(Progress::Note(format!("The tool works, but may not be found from a terminal. {failure}")));
    }

    let mut settings = Settings::read(paths);
    if let Some(folder) = &options.workspace {
        let folder = path::absolute(folder).or_say(|| format!("{} isn't a folder's path", folder.display()))?;
        report(Progress::Started(Stage::MakeWorkspace));
        if tool::workspaces(paths).is_empty() {
            fs::create_dir_all(&folder).or_say(|| format!("{} couldn't be made", folder.display()))?;
            settings.workspace = Some(folder);
        } else {
            report(Progress::Note(format!("The app has workspaces already, so {} wasn't added.", folder.display())));
        }
    }

    // Agents do without the skill, so the rest of the install goes on without it.
    let installed = Record::read(paths).is_some();
    let (done, undone) = match &options.skill {
        Choice::Keep if installed => {
            report(Progress::Started(Stage::UpdateSkill));
            (skill::refresh(paths).map(drop), "wasn't updated")
        }
        Choice::Remove if installed => {
            report(Progress::Started(Stage::RemoveSkill));
            (skill::remove_installed(paths).map(drop), "wasn't removed")
        }
        Choice::Keep | Choice::Remove => (Ok(()), ""),
        Choice::Install { agents, mode } => {
            report(Progress::Started(Stage::InstallSkill));
            let kit = kit.map_or_else(|| Kit::prepare(paths, &mut || {}), Ok);
            (kit.and_then(|kit| kit.install(agents, *mode)), "wasn't installed everywhere")
        }
    };
    if let Err(failure) = done {
        report(Progress::Note(format!("The Agent Skill {undone}. Opening setup again can try again.\n{failure}")));
    }

    report(Progress::Started(Stage::InstallApp));
    let exe = paths.exe();
    copy_exe(&exe)?;
    for (wanted, folder) in
        [(options.shortcuts.desktop, &paths.desktop), (options.shortcuts.start_menu, &paths.start_menu)]
    {
        let shortcut = shortcut(folder);
        if wanted {
            // Windows has both folders already. A sandbox's are made here.
            fs::create_dir_all(folder).or_say(|| format!("{} couldn't be made", folder.display()))?;
            win32::create_shortcut(&shortcut, &exe, &paths.arguments_text(), APP_NAME)
                .or_say(|| format!("The shortcut {} couldn't be made", shortcut.display()))?;
        } else {
            remove_file(&shortcut)?;
        }
    }
    settings.write(paths)?;
    startup::set(paths, options.start_at_sign_in)?;
    register(paths, &exe)?;
    Ok(program)
}

/// Removes the tool, its Agent Skill, and the app. The workspaces, what the tool keeps for the person and its agents,
/// and the agent providers' sign-ins are left alone. `clear` is as for `install`.
pub fn uninstall(
    paths: &Paths,
    report: &mut dyn FnMut(Progress),
    clear: &mut dyn FnMut(&InUse) -> Outcome<Clearing>,
) -> Outcome<()> {
    instance::quit_running(paths)?;
    let uv = tool::find_uv(paths);
    if let Ok(uv) = &uv {
        free_the_tool(uv, paths, report, clear)?;
    }
    // The skill tells agents to run the tool, which is about to go.
    if Record::read(paths).is_some() {
        report(Progress::Started(Stage::RemoveSkill));
        if let Err(failure) = skill::remove_installed(paths) {
            report(Progress::Note(format!("The Agent Skill wasn't removed. {failure}")));
        }
    }
    report(Progress::Started(Stage::RemoveTool));
    if let Err(failure) = uv.and_then(|uv| tool::uninstall(&uv, paths)) {
        report(Progress::Note(format!("The tool wasn't removed. {failure}")));
    }

    report(Progress::Started(Stage::RemoveApp));
    for folder in [&paths.desktop, &paths.start_menu] {
        remove_file(&shortcut(folder))?;
    }
    startup::set(paths, false)?;
    for key in [Some(paths.uninstall_key()), paths.sandbox_registry().map(str::to_owned)].into_iter().flatten() {
        if let Err(error) = CURRENT_USER.remove_tree(&key)
            && error.code() != ERROR_FILE_NOT_FOUND.to_hresult()
        {
            return Err(error).or_say(|| format!("The registry key {key} couldn't be removed"));
        }
    }
    match fs::remove_dir_all(&paths.local) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => {
            return Err(error).or_say(|| format!("{} couldn't be removed", paths.local.display()));
        }
        _ => {}
    }
    remove_exe(paths)
}

/// Returns once nothing runs from the tool, having asked `clear` what to do for as long as something does.
fn free_the_tool(
    uv: &Path,
    paths: &Paths,
    report: &mut dyn FnMut(Progress),
    clear: &mut dyn FnMut(&InUse) -> Outcome<Clearing>,
) -> Outcome<()> {
    let files = tool::files(uv, paths)?;
    loop {
        let in_use = InUse::find(&files)?;
        if in_use.is_empty() {
            return Ok(());
        }
        match clear(&in_use)? {
            Clearing::Wait => thread::sleep(IN_USE_CHECK),
            Clearing::Stop => {
                report(Progress::Started(Stage::Stop));
                in_use.stop()?;
            }
        }
    }
}

/// Refuses to go on while the tool is in use, for an install or uninstall with nobody to ask. `doing` is what it would
/// do to the tool, as in "replaced".
pub fn refuse_in_use(in_use: &InUse, doing: &str) -> Failure {
    Failure::new(format!(
        "The tool is in use by {}, and can't be {doing} until they end. End them, then try again.\n\n{}",
        in_use.said(),
        in_use.programs()
    ))
}

/// Returns whether the exe that is running is the installed one, which is the app, and not a download of it.
pub fn is_installed(paths: &Paths) -> bool {
    env::current_exe().is_ok_and(|running| is_same_place(&running, &paths.exe()))
}

fn shortcut(folder: &Path) -> PathBuf {
    folder.join(format!("{APP_NAME}.lnk"))
}

fn copy_exe(installed: &Path) -> Outcome<()> {
    let running = env::current_exe().or_say(|| "This exe's own path couldn't be read".to_owned())?;
    if is_same_place(&running, installed) {
        return Ok(());
    }
    if let Some(folder) = installed.parent() {
        fs::create_dir_all(folder).or_say(|| format!("{} couldn't be made", folder.display()))?;
    }
    let started = Instant::now();
    while let Err(error) = fs::copy(&running, installed) {
        if started.elapsed() > COPY_PATIENCE {
            return Err(error).or_say(|| format!("The exe couldn't be copied to {}", installed.display()));
        }
        thread::sleep(COPY_CHECK);
    }
    Ok(())
}

fn is_same_place(one: &Path, other: &Path) -> bool {
    match (fs::canonicalize(one), fs::canonicalize(other)) {
        (Ok(one), Ok(other)) => one == other,
        _ => false,
    }
}

fn remove_file(file: &Path) -> Outcome<()> {
    match fs::remove_file(file) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => {
            Err(error).or_say(|| format!("{} couldn't be removed", file.display()))
        }
        _ => Ok(()),
    }
}

/// Lists the app among the installed ones, with what Windows shows about it and how to remove it.
fn register(paths: &Paths, exe: &Path) -> Outcome<()> {
    let path = paths.uninstall_key();
    let failed = || format!("The registry key {path} couldn't be written");
    let key = CURRENT_USER.create(&path).or_say(failed)?;
    for (name, value) in [
        ("DisplayName", APP_NAME),
        (VERSION_VALUE, VERSION),
        ("Publisher", PUBLISHER),
        ("URLInfoAbout", REPOSITORY),
        ("DisplayIcon", &exe.display().to_string()),
        ("InstallLocation", &paths.install.display().to_string()),
        ("UninstallString", &paths.app_text("--uninstall")),
        ("QuietUninstallString", &paths.app_text("--uninstall --quiet")),
    ] {
        key.set_string(name, value).or_say(failed)?;
    }
    let size_kb = fs::metadata(exe).map_or(0, |exe| exe.len() / 1024);
    for (name, value) in [
        ("EstimatedSize", u32::try_from(size_kb).unwrap_or(u32::MAX)),
        // There is nothing to modify or repair, so Windows offers only Uninstall.
        ("NoModify", 1),
        ("NoRepair", 1),
    ] {
        key.set_u32(name, value).or_say(failed)?;
    }
    Ok(())
}

/// Removes the installed exe and its folder, when nothing else is in it.
fn remove_exe(paths: &Paths) -> Outcome<()> {
    let exe = paths.exe();
    let running = env::current_exe().or_say(|| "This exe's own path couldn't be read".to_owned())?;
    if !is_same_place(&running, &exe) {
        remove_file(&exe)?;
        // Fails when something else is in the folder, which is then left.
        let _ = fs::remove_dir(&paths.install);
        return Ok(());
    }
    // Windows won't delete an exe that is running, so a command prompt does it once this one has ended, trying for
    // twenty seconds. `rmdir` without `/s` only removes an empty folder.
    let script = format!(
        "/d /s /c \"(for /l %i in (1,1,20) do if exist \"{exe}\" (del /f /q \"{exe}\" & ping -n 2 127.0.0.1 >nul)) & \
         rmdir \"{folder}\"\"",
        exe = exe.display(),
        folder = paths.install.display()
    );
    Command::new(env::var_os("ComSpec").unwrap_or_else(|| "cmd.exe".into()))
        .raw_arg(script)
        // Not the folder being removed, which a running program would hold in place.
        .current_dir(env::temp_dir())
        // Nothing of this exe's is left open in it, so whatever waits on this exe isn't kept waiting.
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW.0)
        .spawn()
        .or_say(|| format!("{} couldn't be removed", exe.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_agent_providers_chosen_are_the_tools_extras() {
        assert_eq!(Providers::default().extras(), "claude,codex");
        assert_eq!(Providers { claude: false, codex: true }.extras(), "codex");
        assert_eq!(Providers { claude: true, codex: false }.extras(), "claude");
        let pyproject = include_str!("../../pyproject.toml");
        for extra in ["claude", "codex"] {
            assert!(pyproject.lines().any(|line| line.starts_with(&format!("{extra} = ["))), "{extra}");
        }
    }

    #[test]
    fn an_agent_provider_is_named_and_added_to_the_others() {
        let (claude, codex) = (Providers::named("claude").unwrap(), Providers::named("codex").unwrap());
        assert_eq!((claude.extras(), codex.extras()), ("claude".to_owned(), "codex".to_owned()));
        assert_eq!(Providers::named("claude,codex"), None);
        assert_eq!(claude.and(codex), Providers::default());
        assert!(Providers::default().has(codex) && !claude.has(codex) && claude.has(Providers::NONE));
    }

    #[test]
    fn an_update_keeps_the_app_as_it_was_set_up_with_any_agent_provider_added() {
        let existing = |version: Option<&str>| Existing {
            version: version.map(str::to_owned),
            workspaces: Vec::new(),
            skill: None,
            options: Options {
                workspace: Some(PathBuf::from(r"C:\Users\me\Documents\3D Models")),
                agent_providers: Providers::named("claude").unwrap(),
                shortcuts: Shortcuts { desktop: false, start_menu: true },
                start_at_sign_in: true,
                skill: Choice::Keep,
            },
        };
        let kept = existing(Some("0.5.0")).kept(Providers::NONE).unwrap();
        assert_eq!(kept.workspace, None);
        assert_eq!(kept.agent_providers, Providers::named("claude").unwrap());
        assert_eq!((kept.shortcuts, kept.start_at_sign_in), (Shortcuts { desktop: false, start_menu: true }, true));
        let added = existing(Some("0.5.0")).kept(Providers::named("codex").unwrap()).unwrap();
        assert_eq!(added.agent_providers, Providers::default());
        let failure = existing(None).kept(Providers::NONE).unwrap_err();
        assert!(failure.to_string().contains("isn't installed"), "{failure}");
    }

    #[test]
    fn neither_agent_provider_is_refused_before_anything_is_done() {
        let sandbox = env::temp_dir().join(format!("modeling-3d-setup-test-{}-neither", std::process::id()));
        let paths = Paths::current(Some(&sandbox)).unwrap();
        let options = Options { agent_providers: Providers::NONE, ..Options::default() };
        let failure = install(&options, None, &paths, &mut |_| {}, &mut |_| Ok(Clearing::Wait)).unwrap_err();
        assert!(failure.to_string().contains("Choose at least one"), "{failure}");
        assert!(!paths.install.exists() && !paths.local.exists() && !paths.config.exists());
        fs::remove_dir_all(sandbox).unwrap();
    }
}
