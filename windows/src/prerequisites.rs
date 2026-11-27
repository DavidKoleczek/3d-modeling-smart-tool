//! What the tool needs that setup installs when it is missing: uv, which installs the tool and runs it, and which the
//! tool and its agents run to build models.

use std::path::{Path, PathBuf};

use crate::failure::{Failure, Outcome};
use crate::paths::Paths;
use crate::run;

// Astral's own installer, which is what its documentation has people run.
const INSTALL_UV: &str = "irm https://astral.sh/uv/install.ps1 | iex";
// Has that installer put uv in a folder it is told, and leave `PATH` and the rest of the machine alone.
const UV_UNMANAGED_INSTALL: &str = "UV_UNMANAGED_INSTALL";

/// Returns uv, from `PATH` or from where its installer puts it, which a `PATH` read before it ran doesn't have.
pub fn find_uv(paths: &Paths) -> Option<PathBuf> {
    run::find("uv").or_else(|| Some(paths.uv_bin.join("uv.exe")).filter(|uv| uv.is_file()))
}

/// Installs uv for the current user and returns it.
pub fn install_uv(paths: &Paths) -> Outcome<PathBuf> {
    let mut install = powershell(INSTALL_UV, paths)?;
    if paths.is_sandbox() {
        install.env(UV_UNMANAGED_INSTALL, &paths.uv_bin);
    }
    run::output(&mut install)?;
    find_uv(paths).ok_or_else(|| {
        Failure::new(format!("uv was installed, but it isn't in {}. Open setup again.", paths.uv_bin.display()))
    })
}

fn powershell(script: &str, paths: &Paths) -> Outcome<std::process::Command> {
    let powershell = run::find("powershell").ok_or_else(|| Failure::new("PowerShell wasn't found on PATH."))?;
    let mut command = run::hidden(Path::new(&powershell), paths);
    command.args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]);
    // Started from a newer PowerShell, this one is handed that one's modules and can't load its own.
    command.env_remove("PSModulePath");
    Ok(command)
}
