//! Node, which the skills CLI runs on: the one installed when it is new enough, and otherwise the version pinned in
//! `skills/node.json`, downloaded for as long as it is needed.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::failure::{Failure, OrSay, Outcome};
use crate::paths::Paths;
use crate::{run, web, win32};

const PINNED: &str = include_str!("../skills/node.json");
const LOCK: &str = include_str!("../skills/package-lock.json");
// Where the skills CLI is in npm's lock, whose `engines` says the oldest Node it runs on.
const SKILLS_PACKAGE: &str = "node_modules/skills";
// npm as Node's installer and its zip lay it out beside `node.exe`.
const NPM: &str = r"node_modules\npm\bin\npm-cli.js";
const DOWNLOADS: &str = "https://nodejs.org/dist/";
// The zip is some tens of millions of bytes.
const DOWNLOAD_LIMIT: usize = 256 * 1024 * 1024;
const HTTP_OK: u32 = 200;

/// A Node with its npm.
pub struct Node {
    pub exe: PathBuf,
    /// npm's script, which Node runs.
    pub npm: PathBuf,
}

/// Returns the Node on `PATH`, when it is one the skills CLI runs on and npm is beside it.
pub fn installed(paths: &Paths) -> Option<Node> {
    let exe = run::find("node")?;
    let npm = exe.parent()?.join(NPM);
    let said = run::output(run::hidden(&exe, paths).arg("--version")).ok()?;
    let version = numbers(said.trim().trim_start_matches('v'))?;
    (npm.is_file() && version >= numbers(&oldest()?)?).then_some(Node { exe, npm })
}

/// Downloads the pinned Node into a folder, once it is the file the build was made with, and returns it.
pub fn download(folder: &Path, paths: &Paths) -> Outcome<Node> {
    let pinned: Value = serde_json::from_str(PINNED).or_say(|| "skills/node.json couldn't be read".to_owned())?;
    let (Some(version), Some(sha256)) = (pinned["version"].as_str(), pinned["sha256"].as_str()) else {
        return Err(Failure::new("skills/node.json doesn't name a version and its SHA-256."));
    };
    let name = format!("node-v{version}-win-x64");
    let url = format!("{DOWNLOADS}v{version}/{name}.zip");
    let (status, zip) = web::get(&url, DOWNLOAD_LIMIT, paths)?;
    if status != HTTP_OK {
        return Err(Failure::new(format!("{url} answered with the status {status}.")));
    }
    let hash = win32::sha256(&zip).or_say(|| "The download of Node couldn't be checked".to_owned())?;
    let hash = hash.iter().fold(String::new(), |hex, byte| format!("{hex}{byte:02x}"));
    if !hash.eq_ignore_ascii_case(sha256) {
        return Err(Failure::new(format!(
            "The download of Node {version} isn't the file it was built with.\n\nExpected: {sha256}\nDownloaded: {hash}"
        )));
    }

    let file = folder.join(format!("{name}.zip"));
    fs::create_dir_all(folder).or_say(|| format!("{} couldn't be made", folder.display()))?;
    fs::write(&file, zip).or_say(|| format!("{} couldn't be written", file.display()))?;
    // Windows' own tar reads zip files too.
    let tar =
        PathBuf::from(env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into())).join(r"System32\tar.exe");
    run::output(run::hidden(&tar, paths).arg("-xf").arg(&file).arg("-C").arg(folder))?;
    let _ = fs::remove_file(&file);
    let exe = folder.join(&name).join("node.exe");
    let npm = folder.join(&name).join(NPM);
    if !(exe.is_file() && npm.is_file()) {
        return Err(Failure::new(format!("Node's zip didn't have node.exe and npm in {name}.")));
    }
    Ok(Node { exe, npm })
}

/// Returns the oldest Node the pinned skills CLI runs on, from npm's lock of it.
fn oldest() -> Option<String> {
    let lock: Value = serde_json::from_str(LOCK).ok()?;
    let engines = lock["packages"][SKILLS_PACKAGE]["engines"]["node"].as_str()?;
    Some(engines.strip_prefix(">=")?.trim().to_owned())
}

/// Returns the numbers of a version such as `22.20.0`, or None when it is anything else.
fn numbers(version: &str) -> Option<Vec<u64>> {
    version.split('.').map(|part| part.parse().ok()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_oldest_node_comes_from_the_skills_clis_own_lock() {
        let oldest = numbers(&oldest().unwrap()).unwrap();
        assert!(oldest >= vec![22, 0, 0], "{oldest:?}");
    }

    #[test]
    fn the_pinned_node_is_new_enough_and_has_a_hash() {
        let pinned: Value = serde_json::from_str(PINNED).unwrap();
        let version = numbers(pinned["version"].as_str().unwrap()).unwrap();
        assert!(version >= numbers(&oldest().unwrap()).unwrap());
        let hash = pinned["sha256"].as_str().unwrap();
        assert!(hash.len() == 64 && hash.bytes().all(|byte| byte.is_ascii_hexdigit()));
    }

    #[test]
    fn versions_are_compared_by_their_numbers() {
        assert!(numbers("22.20.0") > numbers("22.17.0"));
        assert!(numbers("26.1.0") > numbers("22.20.0"));
        assert_eq!(numbers("v22.0.0"), None);
    }
}
