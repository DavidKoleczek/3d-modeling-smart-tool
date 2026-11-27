//! Where things are on this machine. With `--sandbox` naming a folder, all of it is in that folder, so the exe can be
//! tried without touching what is really installed.

use std::ffi::OsString;
use std::path::{self, Path, PathBuf};
use std::process::Command;
use std::{env, fs, io};

use windows::Win32::UI::Shell::{
    FOLDERID_Desktop, FOLDERID_Documents, FOLDERID_LocalAppData, FOLDERID_Profile, FOLDERID_Programs,
    FOLDERID_RoamingAppData, FOLDERID_UserProgramFiles,
};

use crate::package::APP_NAME;
use crate::win32;

/// The argument that names a sandbox, which every command takes first.
pub const SANDBOX_ARGUMENT: &str = "--sandbox";
const EXE_NAME: &str = "Modeling3D.exe";
// Where Windows keeps what is about the current user's apps, under that user's part of the registry.
const WINDOWS_REGISTRY: &str = r"Software\Microsoft\Windows\CurrentVersion";
// A key Windows reads nothing from, so a sandbox adds no app to its list.
const SANDBOX_REGISTRY: &str = r"Software\Modeling3DSandbox";
const UNINSTALL_KEY: &str = r"Uninstall\Modeling3D";
const RUN_KEY: &str = "Run";
const STARTUP_APPROVED_KEY: &str = r"Explorer\StartupApproved\Run";
// The tool's own name for the folders it keeps the person's settings and its agents' state in.
const TOOL_FOLDER: &str = "modeling-3d";
const INSTANCE: &str = "Modeling3D";
const SANDBOX_INSTANCE: &str = "Modeling3DSandbox";
// Where uv's installer puts it, under the user's own folder.
const UV_BIN: &str = r".local\bin";
// Where uv keeps its downloads and the Pythons it installs, which a sandbox shares rather than fetch again.
const UV_CACHE: &str = r"uv\cache";
const UV_PYTHON: &str = r"uv\python";
// The user's folders as Windows lays them out, which a sandbox's profile copies.
const ROAMING: &str = r"AppData\Roaming";
const LOCAL: &str = r"AppData\Local";
const CLAUDE_HOME: &str = ".claude";
const CODEX_HOME: &str = ".codex";

#[derive(Clone)]
pub struct Paths {
    /// The folder the exe is installed in.
    pub install: PathBuf,
    /// The folder for what the exe keeps for itself and can make again, which uninstalling removes.
    pub local: PathBuf,
    /// The folder the tool keeps the person's settings and workspaces in, and the app its own beside them.
    pub config: PathBuf,
    /// The folder of the Start menu's shortcuts.
    pub start_menu: PathBuf,
    pub desktop: PathBuf,
    /// The folder a first workspace is suggested in.
    pub documents: PathBuf,
    /// The folder Astral's installer puts uv in, where it is looked for when `PATH` doesn't have it yet.
    pub uv_bin: PathBuf,
    /// The user's own folder, which agents keep their skills under.
    pub profile: PathBuf,
    registry: &'static str,
    sandbox: Option<Sandbox>,
}

/// A sandbox's folder, and the folders of uv's own it shares with the machine.
#[derive(Clone)]
struct Sandbox {
    folder: PathBuf,
    uv_cache: PathBuf,
    uv_python: PathBuf,
}

/// The folders Windows knows, which a real install is spread over.
struct KnownFolders {
    programs: PathBuf,
    local_app_data: PathBuf,
    roaming_app_data: PathBuf,
    start_menu: PathBuf,
    desktop: PathBuf,
    documents: PathBuf,
    profile: PathBuf,
}

impl KnownFolders {
    fn find() -> io::Result<Self> {
        Ok(Self {
            programs: win32::known_folder(&FOLDERID_UserProgramFiles)?,
            local_app_data: win32::known_folder(&FOLDERID_LocalAppData)?,
            roaming_app_data: win32::known_folder(&FOLDERID_RoamingAppData)?,
            start_menu: win32::known_folder(&FOLDERID_Programs)?,
            desktop: win32::known_folder(&FOLDERID_Desktop)?,
            documents: win32::known_folder(&FOLDERID_Documents)?,
            profile: win32::known_folder(&FOLDERID_Profile)?,
        })
    }
}

impl Paths {
    /// Returns where things are, in the sandbox when one is named.
    pub fn current(sandbox: Option<&Path>) -> io::Result<Self> {
        let folders = KnownFolders::find()?;
        match sandbox {
            // Named from wherever the exe was started, and what is installed is started from elsewhere.
            Some(folder) => {
                let uv_cache = inherited("UV_CACHE_DIR").unwrap_or_else(|| folders.local_app_data.join(UV_CACHE));
                let uv_python =
                    inherited("UV_PYTHON_INSTALL_DIR").unwrap_or_else(|| folders.roaming_app_data.join(UV_PYTHON));
                let paths = Self::sandboxed(Sandbox { folder: path::absolute(folder)?, uv_cache, uv_python });
                // Codex won't start when `CODEX_HOME` names a folder that isn't there, though it makes its own one.
                fs::create_dir_all(paths.profile.join(CODEX_HOME))?;
                Ok(paths)
            }
            None => Ok(Self::real(folders)),
        }
    }

    fn real(folders: KnownFolders) -> Self {
        Self {
            install: folders.programs.join(APP_NAME),
            local: folders.local_app_data.join(APP_NAME),
            config: folders.roaming_app_data.join(TOOL_FOLDER),
            start_menu: folders.start_menu,
            desktop: folders.desktop,
            documents: folders.documents,
            uv_bin: folders.profile.join(UV_BIN),
            profile: folders.profile,
            registry: WINDOWS_REGISTRY,
            sandbox: None,
        }
    }

    fn sandboxed(sandbox: Sandbox) -> Self {
        let folder = &sandbox.folder;
        let profile = folder.join("profile");
        Self {
            install: folder.join("install"),
            local: folder.join("local"),
            config: profile.join(ROAMING).join(TOOL_FOLDER),
            start_menu: folder.join("start-menu"),
            desktop: folder.join("desktop"),
            documents: folder.join("documents"),
            uv_bin: folder.join("uv"),
            profile,
            registry: SANDBOX_REGISTRY,
            sandbox: Some(sandbox),
        }
    }

    pub fn is_sandbox(&self) -> bool {
        self.sandbox.is_some()
    }

    /// Returns the installed exe.
    pub fn exe(&self) -> PathBuf {
        self.install.join(EXE_NAME)
    }

    /// Returns the arguments the installed exe is given ahead of any other, which name the sandbox when there is one.
    pub fn arguments(&self) -> Vec<OsString> {
        self.sandbox
            .as_ref()
            .map_or_else(Vec::new, |sandbox| vec![SANDBOX_ARGUMENT.into(), sandbox.folder.clone().into_os_string()])
    }

    /// Returns those arguments as they are written in a shortcut or the registry.
    pub fn arguments_text(&self) -> String {
        self.sandbox
            .as_ref()
            .map_or_else(String::new, |sandbox| format!("{SANDBOX_ARGUMENT} \"{}\"", sandbox.folder.display()))
    }

    /// Returns a command that starts the installed exe, in the sandbox when there is one.
    pub fn app(&self) -> Command {
        let mut command = Command::new(self.exe());
        command.args(self.arguments());
        command
    }

    /// Returns the installed exe as Windows is told to start it, with its sandbox, then `arguments`.
    pub fn app_text(&self, arguments: &str) -> String {
        let text = [self.arguments_text(), arguments.to_owned()].into_iter().filter(|text| !text.is_empty());
        [format!("\"{}\"", self.exe().display())].into_iter().chain(text).collect::<Vec<_>>().join(" ")
    }

    /// Returns the registry key, under the current user's, that lists the app among the installed ones.
    pub fn uninstall_key(&self) -> String {
        format!(r"{}\{UNINSTALL_KEY}", self.registry)
    }

    /// Returns the registry key whose values are what Windows starts when the user signs in.
    pub fn run_key(&self) -> String {
        format!(r"{}\{RUN_KEY}", self.registry)
    }

    /// Returns the registry key where Windows notes the startup apps the user has turned off.
    pub fn startup_approved_key(&self) -> String {
        format!(r"{}\{STARTUP_APPROVED_KEY}", self.registry)
    }

    /// Returns the name the running app goes by on this machine, which a sandbox's doesn't share.
    pub fn instance(&self) -> &'static str {
        if self.is_sandbox() { SANDBOX_INSTANCE } else { INSTANCE }
    }

    /// Returns the registry key a sandbox made, which is all its own, and None outside one.
    pub fn sandbox_registry(&self) -> Option<&'static str> {
        self.sandbox.as_ref().map(|_| self.registry)
    }

    /// Returns the variables that keep the tool, its agent providers' sign-ins, and uv's tools inside the sandbox,
    /// and none outside one.
    pub fn environment(&self) -> Vec<(&'static str, OsString)> {
        self.sandbox.as_ref().map_or_else(Vec::new, |sandbox| {
            let folders = [
                // Where the tool keeps the person's settings and workspaces, and its agents' state.
                ("APPDATA", self.profile.join(ROAMING)),
                ("LOCALAPPDATA", self.profile.join(LOCAL)),
                ("CLAUDE_CONFIG_DIR", self.profile.join(CLAUDE_HOME)),
                ("CODEX_HOME", self.profile.join(CODEX_HOME)),
                ("UV_TOOL_DIR", sandbox.folder.join("uv-tools")),
                ("UV_TOOL_BIN_DIR", sandbox.folder.join("uv-bin")),
                // Moving `APPDATA` and `LOCALAPPDATA` would move these too.
                ("UV_CACHE_DIR", sandbox.uv_cache.clone()),
                ("UV_PYTHON_INSTALL_DIR", sandbox.uv_python.clone()),
            ];
            // The agent providers' runtimes start without the person's own settings, which may be what keeps them
            // from sending telemetry.
            let quiet = ["DISABLE_TELEMETRY", "DO_NOT_TRACK", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"];
            let folders = folders.into_iter().map(|(name, folder)| (name, folder.into_os_string()));
            folders.chain(quiet.map(|name| (name, OsString::from("1")))).collect()
        })
    }
}

fn inherited(variable: &str) -> Option<PathBuf> {
    env::var_os(variable).filter(|value| !value.is_empty()).map(PathBuf::from)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn real() -> Paths {
        Paths::real(KnownFolders {
            programs: PathBuf::from(r"C:\Users\me\AppData\Local\Programs"),
            local_app_data: PathBuf::from(r"C:\Users\me\AppData\Local"),
            roaming_app_data: PathBuf::from(r"C:\Users\me\AppData\Roaming"),
            start_menu: PathBuf::from(r"C:\Users\me\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"),
            desktop: PathBuf::from(r"C:\Users\me\OneDrive\Desktop"),
            documents: PathBuf::from("C:/Users/me/OneDrive/Documents"),
            profile: PathBuf::from("C:/Users/me"),
        })
    }

    fn sandboxed() -> Paths {
        Paths::sandboxed(Sandbox {
            folder: PathBuf::from(r"D:\try"),
            uv_cache: PathBuf::from(r"C:\Users\me\AppData\Local\uv\cache"),
            uv_python: PathBuf::from(r"C:\Users\me\AppData\Roaming\uv\python"),
        })
    }

    #[test]
    fn installs_among_the_users_programs() {
        let paths = real();
        assert_eq!(paths.exe(), Path::new(r"C:\Users\me\AppData\Local\Programs\3D Modeling\Modeling3D.exe"));
        assert_eq!(paths.local, Path::new(r"C:\Users\me\AppData\Local\3D Modeling"));
        assert_eq!(paths.config, Path::new(r"C:\Users\me\AppData\Roaming\modeling-3d"));
        assert_eq!(paths.desktop, Path::new(r"C:\Users\me\OneDrive\Desktop"));
        assert_eq!(paths.uv_bin, Path::new(r"C:\Users\me\.local\bin"));
        assert_eq!(paths.uninstall_key(), r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Modeling3D");
        assert_eq!(paths.run_key(), r"Software\Microsoft\Windows\CurrentVersion\Run");
        let approved = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";
        assert_eq!(paths.startup_approved_key(), approved);
        assert!(!paths.is_sandbox());
        assert_eq!(paths.environment(), Vec::new());
        assert_eq!(paths.sandbox_registry(), None);
        assert_eq!(paths.arguments(), Vec::<OsString>::new());
    }

    #[test]
    fn the_exe_is_started_as_windows_is_told_to() {
        let exe = r#""C:\Users\me\AppData\Local\Programs\3D Modeling\Modeling3D.exe""#;
        assert_eq!(real().app_text(""), exe);
        assert_eq!(real().app_text("--background"), format!("{exe} --background"));
        let started = sandboxed().app_text("--background");
        assert_eq!(started, r#""D:\try\install\Modeling3D.exe" --sandbox "D:\try" --background"#);
        assert_eq!(sandboxed().arguments(), [OsString::from("--sandbox"), OsString::from(r"D:\try")]);
    }

    #[test]
    fn a_sandbox_holds_everything_but_uvs_downloads() {
        let paths = sandboxed();
        let sandbox = Path::new(r"D:\try");
        let folders = [&paths.install, &paths.local, &paths.config, &paths.start_menu, &paths.desktop];
        for folder in folders.into_iter().chain([&paths.documents, &paths.uv_bin, &paths.profile]) {
            assert!(folder.starts_with(sandbox), "{}", folder.display());
        }
        let environment = paths.environment();
        let quiet = ["DISABLE_TELEMETRY", "DO_NOT_TRACK", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"];
        for (name, value) in environment.iter().filter(|(name, _)| !quiet.contains(name)) {
            let shared = ["UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"].contains(name);
            assert_eq!(Path::new(value).starts_with(sandbox), !shared, "{name}");
        }
        for name in quiet {
            assert!(environment.contains(&(name, OsString::from("1"))), "{name}");
        }
        // The tool finds its folder from `APPDATA`, as it does outside a sandbox.
        let roaming = environment.into_iter().find(|(name, _)| *name == "APPDATA").unwrap().1;
        assert_eq!(Path::new(&roaming).join(TOOL_FOLDER), paths.config);
        assert!(paths.is_sandbox());
    }

    #[test]
    fn a_sandbox_keeps_out_of_the_keys_windows_reads() {
        let paths = sandboxed();
        assert_eq!(paths.uninstall_key(), r"Software\Modeling3DSandbox\Uninstall\Modeling3D");
        assert_eq!(paths.run_key(), r"Software\Modeling3DSandbox\Run");
        assert_ne!(paths.instance(), real().instance());
        assert_eq!(paths.sandbox_registry(), Some(r"Software\Modeling3DSandbox"));
    }
}
