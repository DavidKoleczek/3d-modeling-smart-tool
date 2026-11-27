//! Running other programs out of sight and reading what they print.

use std::env;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use windows::Win32::System::Threading::CREATE_NO_WINDOW;

use crate::failure::{Failure, OrSay, Outcome};
use crate::paths::Paths;

// As much of what a failed program printed as fits in a message.
const ERROR_LINES: usize = 15;

/// Returns a program on `PATH`, by its name without the `.exe`.
pub fn find(program: &str) -> Option<PathBuf> {
    let name = format!("{program}.exe");
    env::split_paths(&env::var_os("PATH")?).map(|folder| folder.join(&name)).find(|path| path.is_file())
}

/// Returns a command that opens no console window and, in a sandbox, stays inside it.
pub fn hidden(program: &Path, paths: &Paths) -> Command {
    let mut command = Command::new(program);
    command
        .envs(paths.environment())
        // What is printed ends up in messages, where the codes that color a terminal are noise.
        .env("NO_COLOR", "1")
        .stdin(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW.0);
    command
}

/// Runs a command to its end and returns what it printed.
///
/// A failure names the command and says what it printed about going wrong.
pub fn output(command: &mut Command) -> Outcome<String> {
    let said = describe(command);
    let output = command.output().or_say(|| format!("{said} couldn't be started"))?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).into_owned());
    }
    // Some programs, PowerShell among them, say what went wrong where they print everything else.
    let errors = if output.stderr.trim_ascii().is_empty() { &output.stdout } else { &output.stderr };
    let printed = String::from_utf8_lossy(errors);
    let lines: Vec<&str> = printed.lines().filter(|line| !line.trim().is_empty()).collect();
    let last = lines[lines.len().saturating_sub(ERROR_LINES)..].join("\n");
    Err(Failure::new(format!("{said} failed.\n{last}")))
}

/// Returns a command as it would be typed, for saying which one went wrong.
pub fn describe(command: &Command) -> String {
    let program = Path::new(command.get_program()).file_stem().unwrap_or(command.get_program());
    let words: Vec<_> = [program].into_iter().chain(command.get_args()).map(|word| word.to_string_lossy()).collect();
    format!("`{}`", words.join(" "))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_command_is_described_as_it_would_be_typed() {
        let mut command = Command::new(r"C:\tools\uv.exe");
        command.args(["tool", "install"]);
        assert_eq!(describe(&command), "`uv tool install`");
    }
}
