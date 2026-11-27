//! What the app remembers between runs, in `windows-app.json` beside the tool's own settings.

use std::fs;
use std::path::PathBuf;

use serde_json::{Value, json};

use crate::failure::{OrSay, Outcome};
use crate::paths::Paths;

const FILE: &str = "windows-app.json";
/// The port the app asks for, so its address is the same on every machine until something else holds the port.
const FIRST_PORT: u16 = 8788;

#[derive(Clone, Debug, PartialEq)]
pub struct Settings {
    /// The port the app was last served on, which it asks for again so its address stays the same.
    pub port: u16,
    /// The workspace setup chose, which the app opens on the first time it starts, and which the tool remembers from
    /// then on.
    pub workspace: Option<PathBuf>,
}

impl Default for Settings {
    fn default() -> Self {
        Self { port: FIRST_PORT, workspace: None }
    }
}

impl Settings {
    /// Returns what was remembered. Whatever is missing or can't be read is as it is at first.
    pub fn read(paths: &Paths) -> Self {
        fs::read_to_string(file(paths)).map_or_else(|_| Self::default(), |text| Self::from_json(&text))
    }

    pub fn write(&self, paths: &Paths) -> Outcome<()> {
        let file = file(paths);
        let failed = || format!("{} couldn't be written", file.display());
        fs::create_dir_all(&paths.config).or_say(failed)?;
        fs::write(&file, self.to_json()).or_say(failed)
    }

    fn from_json(text: &str) -> Self {
        let read: Value = serde_json::from_str(text).unwrap_or_default();
        let first = Self::default();
        Self {
            port: read["port"]
                .as_u64()
                .and_then(|port| u16::try_from(port).ok())
                .filter(|port| *port != 0)
                .unwrap_or(first.port),
            workspace: read["workspace"].as_str().filter(|folder| !folder.is_empty()).map(PathBuf::from),
        }
    }

    fn to_json(&self) -> String {
        let workspace = self.workspace.as_ref().map(|folder| folder.to_string_lossy());
        format!("{:#}\n", json!({ "port": self.port, "workspace": workspace }))
    }
}

fn file(paths: &Paths) -> PathBuf {
    paths.config.join(FILE)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_is_written_is_read_back() {
        let settings = Settings { port: 51234, workspace: Some(PathBuf::from(r"D:\models")) };
        assert_eq!(Settings::from_json(&settings.to_json()), settings);
        assert_eq!(Settings::from_json(&Settings::default().to_json()), Settings::default());
    }

    #[test]
    fn what_cant_be_read_is_as_it_is_at_first() {
        let first = Settings { port: 8788, workspace: None };
        for text in ["", "not json", "[]", r#"{"port": 0, "workspace": ""}"#, r#"{"port": 70000, "workspace": 5}"#] {
            assert_eq!(Settings::from_json(text), first, "{text}");
        }
    }
}
