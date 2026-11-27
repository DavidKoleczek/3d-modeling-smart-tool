//! The tool's Agent Skill, which tells agents how to use it. The skills CLI's own library lists the agents and
//! installs the skill for them, run on Node from a folder that is there only while it is needed. Where the skill went is
//! kept, so that bringing it up to date and removing it need neither.

use std::path::{Path, PathBuf};
use std::process::{self, Command};
use std::{env, fs};

use serde_json::{Value, json};

use crate::failure::{Failure, OrSay, Outcome};
use crate::node::{self, Node};
use crate::package::SKILL;
use crate::paths::Paths;
use crate::run;

/// The skill's name, which is the folder it is installed in.
const NAME: &str = "modeling-3d";
const FILE: &str = "SKILL.md";
const PACKAGE: &str = include_str!("../skills/package.json");
const LOCK: &str = include_str!("../skills/package-lock.json");
const SCRIPT: &str = include_str!("../skills/skills.mjs");
const SCRIPT_NAME: &str = "skills.mjs";
const RECORD: &str = "skill.json";
// The start of the name of the folder the skills CLI is run from, which ends with the id of the process using it.
const KIT_FOLDER: &str = "skills-";
// What a sandbox's Node is given of this exe's own variables, which Windows programs need to run.
const SYSTEM_VARIABLES: [&str; 6] = ["SystemRoot", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP"];

/// How each agent that reads a folder of its own gets the skill.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub enum Mode {
    /// A link to the one copy in the shared folder.
    #[default]
    Symlink,
    Copy,
}

impl Mode {
    pub fn name(self) -> &'static str {
        match self {
            Self::Symlink => "symlink",
            Self::Copy => "copy",
        }
    }

    pub fn from_name(name: &str) -> Option<Self> {
        [Self::Symlink, Self::Copy].into_iter().find(|mode| mode.name() == name)
    }
}

/// What installing does with the skill.
#[derive(Debug, Default, PartialEq)]
pub enum Choice {
    /// Leaves it where it is, brought up to this version.
    #[default]
    Keep,
    /// Installs it in the shared folder and for these agents, and takes it from the others.
    Install {
        agents: Vec<String>,
        mode: Mode,
    },
    Remove,
}

/// The skills CLI ready to run, in a folder that goes when this does.
pub struct Kit {
    node: Node,
    paths: Paths,
    // Last, so the folder goes once nothing else needs it.
    folder: Scratch,
}

/// A folder that is removed with its value.
struct Scratch(PathBuf);

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

impl Kit {
    /// Gets the skills CLI from npm, to run on the Node installed or else on one downloaded, which `downloading` is
    /// told of before it starts.
    pub fn prepare(paths: &Paths, downloading: &mut dyn FnMut()) -> Outcome<Self> {
        let folder = Scratch(kit_folder(paths));
        let _ = fs::remove_dir_all(&folder.0);
        fs::create_dir_all(&folder.0).or_say(|| format!("{} couldn't be made", folder.0.display()))?;
        let node = if let Some(node) = node::installed(paths) {
            node
        } else {
            downloading();
            node::download(&folder.0.join("node"), paths)?
        };
        for (name, text) in [("package.json", PACKAGE), ("package-lock.json", LOCK), (SCRIPT_NAME, SCRIPT)] {
            let file = folder.0.join(name);
            fs::write(&file, text).or_say(|| format!("{} couldn't be written", file.display()))?;
        }
        let kit = Self { node, paths: paths.clone(), folder };
        // The versions in the lock, each checked against the hash it has there, with nothing of theirs run.
        let mut install = kit.node_command();
        install.arg(&kit.node.npm).args(["ci", "--ignore-scripts", "--no-audit", "--no-fund", "--no-update-notifier"]);
        run::output(install.arg("--cache").arg(kit.folder.0.join("npm-cache")))?;
        Ok(kit)
    }

    /// Returns the agents the skills CLI knows, which of them are on this computer, and which have the skill.
    pub fn agents(&self) -> Outcome<Value> {
        self.ask("agents", None)
    }

    /// Installs the skill in the shared folder and for these agents, takes it from the others, and keeps where it went.
    pub fn install(&self, agents: &[String], mode: Mode) -> Outcome<()> {
        let source = self.folder.0.join("source").join(NAME);
        fs::create_dir_all(&source).or_say(|| format!("{} couldn't be made", source.display()))?;
        fs::write(source.join(FILE), SKILL).or_say(|| format!("{} couldn't be written", source.display()))?;
        let asked = json!({ "source": source.to_string_lossy(), "agents": agents, "mode": mode.name() });
        let answer = self.ask("install", Some(&asked))?;
        Record::from_answer(&answer, mode).write(&self.paths)?;
        failures(&answer)
    }

    /// Removes the skill from every agent, wherever it was installed from.
    pub fn remove(&self) -> Outcome<()> {
        let answer = self.ask("remove", None)?;
        Record::forget(&self.paths)?;
        failures(&answer)
    }

    fn ask(&self, command: &str, given: Option<&Value>) -> Outcome<Value> {
        let mut asking = self.node_command();
        asking.arg(SCRIPT_NAME).arg(command).args(given.map(Value::to_string));
        let printed = run::output(&mut asking)?;
        let line = printed.lines().rfind(|line| !line.trim().is_empty()).unwrap_or_default();
        serde_json::from_str(line).or_say(|| format!("The skills CLI's answer couldn't be read: {line}"))
    }

    fn node_command(&self) -> Command {
        let mut command = run::hidden(&self.node.exe, &self.paths);
        if self.paths.is_sandbox() {
            // Agents are found under the user's folder, and some from variables of their own, so a sandbox's Node is
            // given its folder and none of those.
            command.env_clear();
            for name in SYSTEM_VARIABLES {
                if let Some(value) = env::var_os(name) {
                    command.env(name, value);
                }
            }
            let profile = &self.paths.profile;
            command
                .env("USERPROFILE", profile)
                .env("APPDATA", profile.join(r"AppData\Roaming"))
                .env("LOCALAPPDATA", profile.join(r"AppData\Local"))
                .env("PATH", self.node.exe.parent().unwrap_or(Path::new(".")))
                .envs(self.paths.environment())
                .env("NO_COLOR", "1");
        }
        command.current_dir(&self.folder.0).env("DISABLE_TELEMETRY", "1").env("DO_NOT_TRACK", "1");
        command
    }
}

fn kit_folder(paths: &Paths) -> PathBuf {
    paths.local.join(format!("{KIT_FOLDER}{}", process::id()))
}

/// Removes the folders the skills CLI was run from by exes that ended without removing them, which with Node in them
/// are some hundred megabytes each.
pub fn clear_leftovers(paths: &Paths) {
    let ours = kit_folder(paths);
    for entry in fs::read_dir(&paths.local).into_iter().flatten().flatten() {
        let path = entry.path();
        if path != ours && entry.file_name().to_string_lossy().starts_with(KIT_FOLDER) {
            let _ = fs::remove_dir_all(path);
        }
    }
}

fn failures(answer: &Value) -> Outcome<()> {
    let failed: Vec<&str> = answer["failed"].as_array().into_iter().flatten().filter_map(Value::as_str).collect();
    if failed.is_empty() { Ok(()) } else { Err(Failure::new(failed.join("\n"))) }
}

/// Where the skill was installed, kept so it is brought up to date and removed without the skills CLI.
#[derive(Debug, PartialEq)]
pub struct Record {
    pub mode: Mode,
    /// The agents it is for, as the skills CLI names them.
    pub agents: Vec<String>,
    /// The folders that hold a copy of it.
    folders: Vec<PathBuf>,
    /// The links from where an agent reads it to one of those folders.
    links: Vec<PathBuf>,
}

impl Record {
    pub fn read(paths: &Paths) -> Option<Self> {
        Self::from_json(&fs::read_to_string(paths.local.join(RECORD)).ok()?)
    }

    fn write(&self, paths: &Paths) -> Outcome<()> {
        if self.folders.is_empty() {
            return Self::forget(paths);
        }
        let file = paths.local.join(RECORD);
        let failed = || format!("{} couldn't be written", file.display());
        fs::create_dir_all(&paths.local).or_say(failed)?;
        fs::write(&file, self.to_json()).or_say(failed)
    }

    fn forget(paths: &Paths) -> Outcome<()> {
        let file = paths.local.join(RECORD);
        match fs::remove_file(&file) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => {
                Err(error).or_say(|| format!("{} couldn't be removed", file.display()))
            }
            _ => Ok(()),
        }
    }

    /// Reads where the skills CLI said it installed the skill. A copy is a folder of its own, and a link points to
    /// the shared one.
    fn from_answer(answer: &Value, mode: Mode) -> Self {
        let mut record = Self { mode, agents: texts(&answer["names"]), folders: Vec::new(), links: Vec::new() };
        for target in answer["installed"].as_array().into_iter().flatten() {
            let Some(path) = target["path"].as_str().map(PathBuf::from) else {
                continue;
            };
            let folder = match target["canonicalPath"].as_str().map(PathBuf::from) {
                Some(shared) if target["mode"] == "symlink" && shared != path => {
                    record.links.push(path);
                    shared
                }
                _ => path,
            };
            record.folders.push(folder);
        }
        record.keep_only_the_skill();
        record
    }

    fn from_json(text: &str) -> Option<Self> {
        let read: Value = serde_json::from_str(text).ok()?;
        let paths = |name: &str| texts(&read[name]).into_iter().map(PathBuf::from).collect();
        let mut record = Self {
            mode: Mode::from_name(read["mode"].as_str()?)?,
            agents: texts(&read["agents"]),
            folders: paths("folders"),
            links: paths("links"),
        };
        record.keep_only_the_skill();
        Some(record)
    }

    fn to_json(&self) -> String {
        let shown =
            |paths: &[PathBuf]| paths.iter().map(|path| path.to_string_lossy().into_owned()).collect::<Vec<_>>();
        let record = json!({
            "mode": self.mode.name(),
            "agents": self.agents,
            "folders": shown(&self.folders),
            "links": shown(&self.links),
        });
        format!("{record:#}\n")
    }

    /// Leaves out anything that isn't the skill's own folder, which is all that is ever written or removed.
    fn keep_only_the_skill(&mut self) {
        for paths in [&mut self.folders, &mut self.links] {
            paths.retain(|path| path.is_absolute() && path.file_name().is_some_and(|name| name == NAME));
            paths.sort();
            paths.dedup();
        }
    }
}

fn texts(list: &Value) -> Vec<String> {
    list.as_array().into_iter().flatten().filter_map(Value::as_str).map(str::to_owned).collect()
}

/// Brings the skill up to this version wherever it was installed, and returns whether it was installed anywhere.
pub fn refresh(paths: &Paths) -> Outcome<bool> {
    let Some(record) = Record::read(paths) else {
        return Ok(false);
    };
    for folder in record.folders.iter().filter(|folder| is_folder(folder)) {
        let file = folder.join(FILE);
        fs::write(&file, SKILL).or_say(|| format!("{} couldn't be written", file.display()))?;
    }
    Ok(true)
}

/// Removes the skill from where it was installed, and returns whether it was installed anywhere.
pub fn remove_installed(paths: &Paths) -> Outcome<bool> {
    let Some(record) = Record::read(paths) else {
        return Ok(false);
    };
    for link in &record.links {
        // Removing a link to a folder leaves the folder.
        if fs::symlink_metadata(link).is_ok_and(|link| link.file_type().is_symlink()) {
            fs::remove_dir(link).or_say(|| format!("{} couldn't be removed", link.display()))?;
        }
    }
    for folder in record.folders.iter().filter(|folder| is_folder(folder)) {
        fs::remove_dir_all(folder).or_say(|| format!("{} couldn't be removed", folder.display()))?;
    }
    Record::forget(paths)?;
    Ok(true)
}

/// Whether a path is a folder itself, and not a link to one.
fn is_folder(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|path| path.is_dir())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SHARED: &str = r"C:\Users\me\.agents\skills\modeling-3d";
    const CLAUDE: &str = r"C:\Users\me\.claude\skills\modeling-3d";

    fn answer(mode: &str) -> Value {
        json!({
            "names": ["Claude Code", "Codex"],
            "installed": [
                { "agent": "universal", "mode": mode, "path": SHARED, "canonicalPath": SHARED },
                { "agent": "claude-code", "mode": mode, "path": CLAUDE, "canonicalPath": SHARED },
            ],
            "failed": [],
        })
    }

    #[test]
    fn a_link_points_to_the_shared_copy() {
        let record = Record::from_answer(&answer("symlink"), Mode::Symlink);
        assert_eq!(record.folders, [PathBuf::from(SHARED)]);
        assert_eq!(record.links, [PathBuf::from(CLAUDE)]);
        assert_eq!(record.agents, ["Claude Code", "Codex"]);
    }

    #[test]
    fn a_copy_is_a_folder_of_its_own() {
        let record = Record::from_answer(&answer("copy"), Mode::Copy);
        assert_eq!(record.folders, [PathBuf::from(SHARED), PathBuf::from(CLAUDE)]);
        assert_eq!(record.links, Vec::<PathBuf>::new());
    }

    #[test]
    fn what_is_kept_is_read_back() {
        let record = Record::from_answer(&answer("symlink"), Mode::Symlink);
        assert_eq!(Record::from_json(&record.to_json()), Some(record));
        assert_eq!(Record::from_json(r#"{"mode": "hardlink", "folders": []}"#), None);
        assert_eq!(Record::from_json("not json"), None);
    }

    #[test]
    fn nothing_but_the_skills_own_folder_is_ever_touched() {
        let text = json!({
            "mode": "copy",
            "folders": [SHARED, r"C:\Users\me\.agents\skills", r"C:\Users\me", "modeling-3d", ""],
            "links": [r"C:\Users\me\.claude\skills"],
        });
        let record = Record::from_json(&text.to_string()).unwrap();
        assert_eq!(record.folders, [PathBuf::from(SHARED)]);
        assert_eq!(record.links, Vec::<PathBuf>::new());
    }

    #[test]
    fn modes_go_by_the_skills_clis_names() {
        for mode in [Mode::Symlink, Mode::Copy] {
            assert_eq!(Mode::from_name(mode.name()), Some(mode));
        }
        let script = include_str!("../skills/skills.mjs");
        for command in ["agents", "install", "remove"] {
            assert!(script.contains(&format!("async function {command}(")), "{command}");
        }
    }

    #[test]
    fn failures_are_said_together() {
        assert!(failures(&answer("copy")).is_ok());
        let failed = failures(&json!({ "failed": ["one", "two"] })).unwrap_err().to_string();
        assert_eq!(failed, "one\ntwo");
    }
}
