//! Newer versions of the app: looking for one among the repository's releases on GitHub, and having its exe put
//! itself in this one's place.

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::{env, fs};

use serde_json::Value;

use crate::failure::{Failure, OrSay, Outcome};
use crate::package::{APP_NAME, REPOSITORY, VERSION};
use crate::paths::Paths;
use crate::{web, win32};

/// The argument a newer exe is started with to install itself over the app that downloaded it.
pub const UPDATE: &str = "--update";
/// In a sandbox, an address to ask in place of GitHub's, which answers about a latest release as GitHub does.
pub const SANDBOX_RELEASE_VARIABLE: &str = "MODELING_3D_SANDBOX_RELEASE";
// The name the exe is built under, which is the one it has in a release.
const INSTALLER: &str = concat!(env!("CARGO_BIN_NAME"), ".exe");
const GITHUB: &str = "https://github.com/";
const GITHUB_API: &str = "https://api.github.com/repos/";
// How GitHub writes the hash it publishes for a file of a release, and the length of the hash in hex.
const DIGEST_KIND: &str = "sha256:";
const DIGEST_LENGTH: usize = 64;
// GitHub's answer about a release is some thousands of bytes, and the exe a few million.
const RELEASE_LIMIT: usize = 4 * 1024 * 1024;
const INSTALLER_LIMIT: usize = 256 * 1024 * 1024;
const DOWNLOADS: &str = "updates";
const HTTP_OK: u32 = 200;
const HTTP_NOT_FOUND: u32 = 404;

/// A version of the app newer than this one, and where its exe is.
#[derive(Clone, Debug, PartialEq)]
pub struct Update {
    pub version: String,
    url: String,
    /// The SHA-256 hash GitHub publishes for the exe, in hex.
    sha256: String,
}

/// Asks GitHub for the latest release, and returns it when it is newer than this exe.
pub fn check(paths: &Paths) -> Outcome<Option<Update>> {
    let asked = latest_release(paths);
    let (status, answer) = web::get(&asked, RELEASE_LIMIT, paths)?;
    match status {
        HTTP_OK => newer(&String::from_utf8_lossy(&answer), VERSION),
        // What GitHub answers for a repository that has no release yet.
        HTTP_NOT_FOUND => Ok(None),
        _ => Err(Failure::new(format!("{asked} answered with the status {status}."))),
    }
}

/// Removes the exes earlier updates were made from. One still running is left for the next time.
pub fn clear_downloads(paths: &Paths) {
    let _ = fs::remove_dir_all(paths.local.join(DOWNLOADS));
}

impl Update {
    /// Downloads the newer exe and starts it, which has it ask this app to quit and take its place.
    ///
    /// Returns only when that didn't happen: with a failure when the exe couldn't be had or started, and without one
    /// when it ended early, having said why in a window of its own.
    pub fn install(&self, paths: &Paths) -> Outcome<()> {
        let exe = self.download(paths)?;
        let failed = || format!("{} couldn't be started", exe.display());
        let mut newer = Command::new(&exe);
        newer.args(paths.arguments()).arg(UPDATE).stdin(Stdio::null());
        newer.spawn().or_say(failed)?.wait().or_say(failed)?;
        Ok(())
    }

    /// Downloads the newer exe, and keeps it only when it is the file GitHub published.
    fn download(&self, paths: &Paths) -> Outcome<PathBuf> {
        let (status, exe) = web::get(&self.url, INSTALLER_LIMIT, paths)?;
        if status != HTTP_OK {
            return Err(Failure::new(format!("{} answered with the status {status}.", self.url)));
        }
        let hash = win32::sha256(&exe).or_say(|| "The download couldn't be checked".to_owned())?;
        let hash = hash.iter().fold(String::new(), |hex, byte| format!("{hex}{byte:02x}"));
        if !hash.eq_ignore_ascii_case(&self.sha256) {
            return Err(Failure::new(format!(
                "The download of version {} isn't the file GitHub published.\n\n\
                 Published: {}\nDownloaded: {hash}",
                self.version, self.sha256
            )));
        }
        clear_downloads(paths);
        let folder = paths.local.join(DOWNLOADS);
        let file = folder.join(format!("{APP_NAME} {}.exe", self.version));
        let failed = || format!("{} couldn't be written", file.display());
        fs::create_dir_all(&folder).or_say(failed)?;
        fs::write(&file, exe).or_say(failed)?;
        Ok(file)
    }
}

/// Returns the address that answers about the latest release.
fn latest_release(paths: &Paths) -> String {
    let instead = env::var(SANDBOX_RELEASE_VARIABLE).ok().filter(|address| paths.is_sandbox() && !address.is_empty());
    instead.unwrap_or_else(|| githubs_latest_release(REPOSITORY))
}

fn githubs_latest_release(repository: &str) -> String {
    format!("{GITHUB_API}{}/releases/latest", repository.trim_start_matches(GITHUB).trim_end_matches('/'))
}

/// Reads GitHub's answer about a release, and returns the release when it is newer than a version.
///
/// A newer release without the exe, or without a hash for it, is a failure: a release is there a moment before its
/// files are.
fn newer(release: &str, than: &str) -> Outcome<Option<Update>> {
    let release: Value = serde_json::from_str(release).or_say(|| "GitHub's answer couldn't be read".to_owned())?;
    // A tag that isn't a version is a release of something else.
    let tag = release["tag_name"].as_str().unwrap_or_default();
    let version = tag.strip_prefix('v').unwrap_or(tag);
    let (Some(latest), Some(than)) = (numbers(version), numbers(than)) else {
        return Ok(None);
    };
    if latest <= than {
        return Ok(None);
    }
    let installer = release["assets"].as_array().into_iter().flatten().find(|asset| asset["name"] == INSTALLER);
    let found = installer.and_then(|asset| {
        let hash = asset["digest"].as_str()?.strip_prefix(DIGEST_KIND)?;
        let is_hash = hash.len() == DIGEST_LENGTH && hash.bytes().all(|byte| byte.is_ascii_hexdigit());
        is_hash.then_some((asset["browser_download_url"].as_str()?, hash))
    });
    match found {
        Some((url, hash)) => {
            Ok(Some(Update { version: version.to_owned(), url: url.to_owned(), sha256: hash.to_owned() }))
        }
        None => Err(Failure::new(format!(
            "Version {version} is out, but {INSTALLER} isn't in its release yet. Try again in a while."
        ))),
    }
}

/// Returns the numbers of a version such as `0.2.0`, without the zeros it ends with, so that `1.0` and `1.0.0` are
/// the same. None when it has anything but digits and dots.
fn numbers(version: &str) -> Option<Vec<u64>> {
    let number = |part: &str| part.parse().ok().filter(|_| part.bytes().all(|byte| byte.is_ascii_digit()));
    let mut numbers = version.split('.').map(number).collect::<Option<Vec<u64>>>()?;
    while numbers.last() == Some(&0) {
        numbers.pop();
    }
    Some(numbers)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    const HASH: &str = "9f86d081884c7d659a2feae0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";
    const URL: &str = "https://github.com/me/3d-modeling-smart-tool/releases/download/v0.6.0/Modeling3DSetup.exe";

    fn release(tag: &str, assets: &Value) -> String {
        json!({ "tag_name": tag, "name": tag, "assets": assets }).to_string()
    }

    fn installer(digest: &str) -> Value {
        json!([
            { "name": "notes.txt", "browser_download_url": "https://github.com/notes.txt", "digest": "sha256:00" },
            { "name": "Modeling3DSetup.exe", "browser_download_url": URL, "digest": digest },
        ])
    }

    #[test]
    fn versions_are_compared_by_their_numbers() {
        assert!(numbers("0.10.0") > numbers("0.9.1"));
        assert!(numbers("1.0.0") > numbers("0.99.99"));
        assert_eq!(numbers("1.0"), numbers("1.0.0"));
        for not_one in ["0.6.0rc1", "+0.6.0", "0..6", "latest", ""] {
            assert_eq!(numbers(not_one), None, "{not_one}");
        }
    }

    #[test]
    fn a_newer_release_is_an_update_with_its_exe_and_hash() {
        let found = newer(&release("v0.6.0", &installer(&format!("sha256:{HASH}"))), "0.5.0").unwrap();
        let update = Update { version: "0.6.0".to_owned(), url: URL.to_owned(), sha256: HASH.to_owned() };
        assert_eq!(found, Some(update));
    }

    #[test]
    fn a_release_that_is_not_newer_is_no_update() {
        let assets = installer(&format!("sha256:{HASH}"));
        for (tag, than) in [("v0.6.0", "0.6.0"), ("v0.6.0", "0.7.0"), ("v0.6", "0.6.0"), ("nightly", "0.5.0")] {
            assert_eq!(newer(&release(tag, &assets), than).unwrap(), None, "{tag} after {than}");
        }
    }

    #[test]
    fn a_newer_release_without_the_exe_or_its_hash_is_a_failure() {
        for assets in [json!([]), installer("md5:00"), installer("sha256:abc"), installer(&format!("sha256:{HASH}zz"))]
        {
            let failure = newer(&release("v0.6.0", &assets), "0.5.0").unwrap_err().to_string();
            assert!(failure.contains("Version 0.6.0 is out"), "{failure}");
        }
        assert!(newer("<html>", "0.5.0").is_err());
    }

    #[test]
    fn the_latest_release_is_asked_of_githubs_api() {
        let asked = githubs_latest_release("https://github.com/me/3d-modeling-smart-tool");
        assert_eq!(asked, "https://api.github.com/repos/me/3d-modeling-smart-tool/releases/latest");
        let ours = githubs_latest_release(REPOSITORY);
        assert!(ours.starts_with(GITHUB_API) && ours.ends_with("/releases/latest") && !ours.contains("//releases"));
    }

    #[test]
    fn the_release_is_built_under_the_name_it_is_published_as() {
        assert_eq!(INSTALLER, "Modeling3DSetup.exe");
    }
}
