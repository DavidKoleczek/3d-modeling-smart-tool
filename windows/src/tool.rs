//! The tool itself, which uv installs from the wheel the exe carries.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::failure::{Failure, OrSay, Outcome};
use crate::in_use::ToolFiles;
use crate::install::Providers;
use crate::package::{CONSTRAINTS, PYTHON_VERSION, VERSION, WHEEL, WHEEL_NAME};
use crate::paths::Paths;
use crate::{prerequisites, run};

const TOOL: &str = "modeling-3d";
const WORKSPACES: &str = "app-workspaces.json";
// The package each agent provider's extra brings, as its folder among the tool's packages.
const CLAUDE_PACKAGE: &str = "claude_agent_sdk";
const CODEX_PACKAGE: &str = "openai_codex";
const PACKAGES: &str = r"Lib\site-packages";

/// Returns uv, which installs the tool and knows where it is.
pub fn find_uv(paths: &Paths) -> Outcome<PathBuf> {
    prerequisites::find_uv(paths)
        .ok_or_else(|| Failure::new("uv isn't installed, and the tool runs on it. Setup installs it again."))
}

/// Installs this exe's version of the tool, with the agent providers chosen, in place of any other, and returns its
/// program.
pub fn install(uv: &Path, providers: Providers, paths: &Paths) -> Outcome<PathBuf> {
    // uv takes a wheel and its pins as files. It looks for the wheel there again on `uv tool upgrade`, which fails
    // without it, so the wheel stays, and the one of the version before goes.
    let package = paths.local.join("package");
    let wheel = package.join(WHEEL_NAME);
    let constraints = package.join("constraints.txt");
    let _ = fs::remove_dir_all(&package);
    fs::create_dir_all(&package).or_say(|| format!("{} couldn't be made", package.display()))?;
    fs::write(&wheel, WHEEL).or_say(|| format!("{} couldn't be written", wheel.display()))?;
    fs::write(&constraints, CONSTRAINTS).or_say(|| format!("{} couldn't be written", constraints.display()))?;
    let mut wanted = wheel.into_os_string();
    wanted.push(format!("[{}]", providers.extras()));
    run::output(
        run::hidden(uv, paths)
            .args(["tool", "install", "--force", "--python", PYTHON_VERSION])
            .arg(wanted)
            .arg("--constraints")
            .arg(&constraints),
    )?;

    let tool = program(uv, paths)?;
    let version = run::output(run::hidden(&tool, paths).arg("--version"))?;
    if version.trim() != format!("{TOOL} {VERSION}") {
        return Err(Failure::new(format!(
            "{} says it is `{}`, not version {VERSION}, after it was installed.",
            tool.display(),
            version.trim()
        )));
    }
    Ok(tool)
}

/// Returns the tool's program, which is where uv keeps the programs of the tools it has installed.
pub fn program(uv: &Path, paths: &Paths) -> Outcome<PathBuf> {
    let tool = bin(uv, paths)?.join(format!("{TOOL}.exe"));
    if !tool.is_file() {
        return Err(Failure::new(format!(
            "The tool isn't installed: {} isn't there. Setup installs it again.",
            tool.display()
        )));
    }
    Ok(tool)
}

/// Returns the folder uv puts the programs of its tools in.
pub fn bin(uv: &Path, paths: &Paths) -> Outcome<PathBuf> {
    let folder = run::output(run::hidden(uv, paths).args(["tool", "dir", "--bin"]))?;
    Ok(PathBuf::from(folder.trim()))
}

/// Returns where the tool's programs are, whether or not it is installed.
pub fn files(uv: &Path, paths: &Paths) -> Outcome<ToolFiles> {
    let tools = run::output(run::hidden(uv, paths).args(["tool", "dir"]))?;
    Ok(ToolFiles {
        environment: Path::new(tools.trim()).join(TOOL),
        program: bin(uv, paths)?.join(format!("{TOOL}.exe")),
    })
}

/// Returns which agent providers the installed tool has, or None when it isn't installed.
pub fn installed_providers(tool: &ToolFiles) -> Option<Providers> {
    let packages = tool.environment.join(PACKAGES);
    packages.is_dir().then(|| Providers {
        claude: packages.join(CLAUDE_PACKAGE).is_dir(),
        codex: packages.join(CODEX_PACKAGE).is_dir(),
    })
}

/// Puts the folder of uv's tools on the user's `PATH`, so a terminal and an agent find the tool.
pub fn put_on_path(uv: &Path, paths: &Paths) -> Outcome<()> {
    run::output(run::hidden(uv, paths).args(["tool", "update-shell"])).map(drop)
}

pub fn uninstall(uv: &Path, paths: &Paths) -> Outcome<()> {
    run::output(run::hidden(uv, paths).args(["tool", "uninstall", TOOL])).map(drop)
}

/// Returns the workspaces opened in the app, newest first. The tool's own file says so, which uninstalling leaves,
/// so they are known of before the tool is there to ask.
pub fn workspaces(paths: &Paths) -> Vec<PathBuf> {
    fs::read_to_string(paths.config.join(WORKSPACES)).map_or_else(|_| Vec::new(), |opened| listed(&opened))
}

fn listed(opened: &str) -> Vec<PathBuf> {
    let opened: Value = serde_json::from_str(opened).unwrap_or_default();
    let workspaces = opened["workspaces"].as_array().into_iter().flatten();
    workspaces.filter_map(Value::as_str).map(PathBuf::from).collect()
}

/// How an agent provider is signed in, as the tool says.
#[derive(Debug, PartialEq)]
pub struct ProviderStatus {
    pub agent_provider: String,
    pub installed: bool,
    /// How it is signed in, or None when it isn't.
    pub signed_in_with: Option<String>,
    /// What keeps it from running, and what fixes it.
    pub problem: Option<String>,
}

/// Asks the tool how each agent provider is signed in, which takes a second or two.
pub fn agent_providers(tool: &Path, paths: &Paths) -> Outcome<Vec<ProviderStatus>> {
    let listed = run::output(run::hidden(tool, paths).arg("list-agent-providers"))?;
    statuses(&listed)
        .ok_or_else(|| Failure::new(format!("The tool's list of agent providers couldn't be read: {listed}")))
}

fn statuses(listed: &str) -> Option<Vec<ProviderStatus>> {
    let listed: Value = serde_json::from_str(listed).ok()?;
    let text = |value: &Value| value.as_str().map(str::to_owned);
    listed["agent_providers"]
        .as_array()?
        .iter()
        .map(|status| {
            Some(ProviderStatus {
                agent_provider: text(&status["agent_provider"])?,
                installed: status["installed"].as_bool()?,
                signed_in_with: status["signed_in"].as_bool()?.then(|| text(&status["signed_in_with"])).flatten(),
                problem: text(&status["problem"]),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspaces_are_known_of_from_the_tools_own_file() {
        let opened = r#"{"workspaces": ["D:\\models", "C:\\Users\\me\\game"]}"#;
        assert_eq!(listed(opened), [PathBuf::from(r"D:\models"), PathBuf::from(r"C:\Users\me\game")]);
        for nothing in [r#"{"workspaces": []}"#, r#"{"recent": ["D:\\models"]}"#, "not JSON"] {
            assert_eq!(listed(nothing), Vec::<PathBuf>::new(), "{nothing}");
        }
    }

    #[test]
    fn the_agent_providers_are_read_as_the_tool_lists_them() {
        let listed = r#"{"agent_providers": [
            {"agent_provider": "claude", "installed": true, "signed_in": true, "signed_in_with": "Claude Max",
             "problem": null},
            {"agent_provider": "codex", "installed": true, "signed_in": false, "signed_in_with": null,
             "problem": "Codex is not signed in."}
        ]}"#;
        let read = statuses(listed).unwrap();
        assert_eq!(read[0].signed_in_with.as_deref(), Some("Claude Max"));
        assert_eq!(
            (read[1].signed_in_with.as_deref(), read[1].problem.as_deref()),
            (None, Some("Codex is not signed in."))
        );
        assert!(statuses(r#"{"agent_providers": [{}]}"#).is_none());
        assert!(statuses("[]").is_none());
    }

    #[test]
    fn the_providers_installed_are_the_packages_there() {
        let folder = std::env::temp_dir().join(format!("modeling-3d-setup-test-{}", std::process::id()));
        let tool = ToolFiles { environment: folder.join(TOOL), program: folder.join("modeling-3d.exe") };
        assert_eq!(installed_providers(&tool), None);
        fs::create_dir_all(tool.environment.join(PACKAGES).join(CODEX_PACKAGE)).unwrap();
        assert_eq!(installed_providers(&tool), Some(Providers { claude: false, codex: true }));
        fs::remove_dir_all(folder).unwrap();
    }
}
