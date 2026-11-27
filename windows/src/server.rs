//! The app's server, which is the tool run as `modeling-3d app`, out of sight, for as long as the app wants it.

use std::collections::VecDeque;
use std::env;
use std::ffi::{OsStr, OsString};
use std::io::{BufRead, BufReader, Read};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::process::{Child, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use crate::control::Control;
use crate::failure::{OrSay, Outcome};
use crate::paths::Paths;
use crate::run;
use crate::settings::Settings;
use crate::win32::Job;

// As much of what a server that ended printed about it as fits in a message.
const ERROR_LINES: usize = 15;
// A server on this machine answers at once, and Windows takes seconds to say that nothing is there.
const CONNECT_PATIENCE: Duration = Duration::from_millis(200);
const STOP_PATIENCE: Duration = Duration::from_secs(5);
const STOP_CHECK: Duration = Duration::from_millis(50);

/// What a server tells of itself, once each and in this order. One that never listens only ends.
#[derive(Debug)]
pub enum Heard {
    /// It is serving the app at this address.
    Listening(String),
    /// It ended, and this is what it printed about why, if anything.
    Ended(String),
}

/// A running server. Dropping it ends it, as does this exe ending in any way. The runs it starts leave it, and go on.
pub struct Server {
    process: Child,
    job: Job,
    port: u16,
}

impl Server {
    /// Starts the server on the port in the settings, on their workspace when they have one, and returns before it
    /// listens. `control` is how the server reaches this app. `hear` is told what becomes of the server, from a thread
    /// of its own.
    pub fn start(
        tool: &Path,
        uv: &Path,
        settings: &Settings,
        paths: &Paths,
        control: &Control,
        hear: impl Fn(Heard) + Send + 'static,
    ) -> Outcome<Self> {
        let mut command = run::hidden(tool, paths);
        command.envs(control.environment()).args(["app", "--port", &settings.port.to_string()]);
        if let Some(workspace) = &settings.workspace {
            command.arg("--workspace").arg(workspace);
        }
        // The tool and its agents run uv and the tool by name, which a `PATH` read before setup put them on doesn't
        // have, as the app's can be when it starts at sign-in.
        if let Some(path) = with_first(&[uv, tool], env::var_os("PATH").as_deref()) {
            command.env("PATH", path);
        }
        let said = run::describe(&command);
        let failed = || format!("{said} couldn't be started");
        let job = Job::new().or_say(failed)?;
        let mut process = command.stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().or_say(failed)?;
        // The tool's program starts Python and ties it to itself, so ending this one process ends the server.
        if let Err(error) = job.add(&process) {
            let _ = process.kill();
            return Err(error).or_say(failed);
        }
        if let (Some(printed), Some(errors)) = (process.stdout.take(), process.stderr.take()) {
            thread::spawn(move || listen(printed, errors, &hear));
        }
        Ok(Self { process, job, port: settings.port })
    }

    /// Ends the server and returns once its port is free again, so the next one can have it.
    pub fn stop(mut self) {
        let _ = self.job.end();
        let _ = self.process.wait();
        // Python goes a moment after the tool's program does.
        let started = Instant::now();
        while !is_free(self.port) && started.elapsed() < STOP_PATIENCE {
            thread::sleep(STOP_CHECK);
        }
    }
}

/// Returns a `PATH` with the folders of these programs first, or None when one can't be written in a `PATH`.
fn with_first(programs: &[&Path], path: Option<&OsStr>) -> Option<OsString> {
    let first = programs.iter().filter_map(|program| program.parent()).map(Path::to_path_buf);
    let rest: Vec<_> = path.into_iter().flat_map(env::split_paths).collect();
    env::join_paths(first.chain(rest)).ok()
}

/// Returns the port to serve on: the one asked for, or a free one when something else has it.
pub fn free_port(wanted: u16) -> Outcome<u16> {
    if is_free(wanted) {
        return Ok(wanted);
    }
    TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .or_say(|| "No free port was found for the app".to_owned())
}

/// Whether nothing on this machine listens on the port or holds it.
///
/// Only this machine's own address is tried, since trying the network's would have Windows Firewall ask about this
/// exe.
fn is_free(port: u16) -> bool {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    // A program listening on every address leaves this one free to bind, so it is found by reaching it.
    TcpStream::connect_timeout(&address, CONNECT_PATIENCE).is_err() && TcpListener::bind(address).is_ok()
}

/// Reads what the server prints until it ends, which is when both it and Python have.
fn listen(printed: impl Read, errors: impl Read + Send + 'static, hear: &impl Fn(Heard)) {
    let errors = thread::spawn(move || last_lines(errors));
    let mut lines = BufReader::new(printed).lines().map_while(Result::ok);
    // The tool prints the app's address first. Whatever follows is for a person at a terminal.
    if let Some(url) = lines.next() {
        hear(Heard::Listening(url));
    }
    lines.for_each(drop);
    hear(Heard::Ended(errors.join().unwrap_or_default()));
}

/// Reads to the end, so the server is never kept waiting to print, and returns the last of it.
fn last_lines(printed: impl Read) -> String {
    let mut last = VecDeque::with_capacity(ERROR_LINES);
    for line in BufReader::new(printed).lines().map_while(Result::ok).filter(|line| !line.trim().is_empty()) {
        if last.len() == ERROR_LINES {
            last.pop_front();
        }
        last.push_back(line);
    }
    Vec::from(last).join("\n")
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;

    use super::*;

    fn heard(printed: &'static str, errors: &'static str) -> Vec<String> {
        let (sender, receiver) = mpsc::channel();
        listen(printed.as_bytes(), errors.as_bytes(), &move |heard| sender.send(format!("{heard:?}")).unwrap());
        receiver.iter().collect()
    }

    #[test]
    fn a_server_is_heard_listening_at_the_first_address_it_prints_and_then_ending() {
        let all = heard("http://127.0.0.1:8788\nsomething for a person\n", "");
        assert_eq!(all, [r#"Listening("http://127.0.0.1:8788")"#, r#"Ended("")"#]);
    }

    #[test]
    fn a_server_that_never_listens_ends_with_what_it_said() {
        let all = heard("", "\nThe port 8788 is held by another program.\n");
        assert_eq!(all, [r#"Ended("The port 8788 is held by another program.")"#]);
    }

    #[test]
    fn only_the_last_of_what_was_printed_is_kept() {
        let printed = (1..=40).map(|line| format!("line {line}")).collect::<Vec<_>>().join("\n");
        let last = last_lines(printed.as_bytes());
        assert_eq!(last.lines().count(), ERROR_LINES);
        assert!(last.starts_with("line 26\n") && last.ends_with("line 40"));
    }

    #[test]
    fn uv_and_the_tool_are_found_first_on_the_servers_path() {
        let uv = Path::new(r"C:\Users\me\.local\bin\uv.exe");
        let tool = Path::new(r"D:\try\uv-bin\modeling-3d.exe");
        let path = with_first(&[uv, tool], Some(OsStr::new(r"C:\Windows;C:\Tools"))).unwrap();
        assert_eq!(path, OsString::from(r"C:\Users\me\.local\bin;D:\try\uv-bin;C:\Windows;C:\Tools"));
        assert_eq!(with_first(&[uv], None).unwrap(), OsString::from(r"C:\Users\me\.local\bin"));
    }

    #[test]
    fn a_port_something_listens_on_is_not_free_and_another_is_found() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let held = listener.local_addr().unwrap().port();
        assert!(!is_free(held));
        let found = free_port(held).unwrap();
        assert_ne!(found, held);
        drop(listener);
        assert_eq!(free_port(held).unwrap(), held);
    }
}
