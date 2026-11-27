//! What runs from the installed tool. Replacing or removing the tool has to wait for it to end: uv deletes the tool's
//! packages before it finds a program it can't remove, and leaves the tool broken.

use std::collections::HashSet;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::failure::{OrSay, Outcome};
use crate::win32::{self, Process};

// How long the processes being stopped get to end.
const STOP_PATIENCE: Duration = Duration::from_secs(15);
// The program of a run: each starts the tool's own Python.
const PYTHON: [&str; 2] = ["python.exe", "pythonw.exe"];

/// Where the installed tool's programs are.
pub struct ToolFiles {
    /// The tool's environment, which holds its Python, its packages, and the agent providers' runtimes.
    pub environment: PathBuf,
    /// The tool's program on `PATH`, which uv keeps beside the environment.
    pub program: PathBuf,
}

/// What runs from the tool, and everything those started.
#[derive(Debug, Default)]
pub struct InUse {
    /// The tool's runs, each in a Python of its own, building or checking a model.
    pub runs: usize,
    /// The rest, such as the MCP server of an agent session, or a command run in a terminal.
    pub others: usize,
    processes: Vec<Process>,
}

impl InUse {
    /// Looks at what is running now.
    pub fn find(tool: &ToolFiles) -> Outcome<Self> {
        let processes = win32::processes().or_say(|| "What runs from the tool couldn't be listed".to_owned())?;
        Ok(Self::among(&processes, tool))
    }

    fn among(processes: &[Process], tool: &ToolFiles) -> Self {
        let from_tool: Vec<&Process> = processes
            .iter()
            .filter(|process| process.program.as_deref().is_some_and(|program| is_of(program, tool)))
            .collect();
        // What they started goes with them, wherever its program is, such as the Python a run's starts.
        let mut kept: HashSet<u32> = from_tool.iter().map(|process| process.id).collect();
        let mut stopping: Vec<Process> = from_tool.iter().copied().cloned().collect();
        loop {
            let started_by_them: Vec<&Process> = processes
                .iter()
                .filter(|process| !kept.contains(&process.id))
                .filter(|process| stopping.iter().any(|parent| started(parent, process)))
                .collect();
            if started_by_them.is_empty() {
                break;
            }
            kept.extend(started_by_them.iter().map(|process| process.id));
            stopping.extend(started_by_them.into_iter().cloned());
        }
        let mut found = Self::default();
        for process in from_tool {
            // Each run and session is a tree of processes, counted once, by the first of the tool's programs in it.
            if stopping.iter().any(|other| started(other, process)) {
                continue;
            }
            if process.program.as_deref().and_then(Path::file_name).is_some_and(is_python) {
                found.runs += 1;
            } else {
                found.others += 1;
            }
        }
        found.processes = stopping;
        found
    }

    pub fn is_empty(&self) -> bool {
        self.processes.is_empty()
    }

    /// Ends all of it, and returns once it has ended.
    pub fn stop(&self) -> Outcome<()> {
        win32::end_processes(&self.processes, STOP_PATIENCE)
            .or_say(|| "What runs from the tool couldn't all be stopped".to_owned())
    }

    /// Says what runs, as in "2 runs and 1 agent session or command".
    pub fn said(&self) -> String {
        let runs = counted(self.runs, "run", "runs");
        let others = counted(self.others, "agent session or command", "agent sessions or commands");
        let said: Vec<String> = [runs, others].into_iter().flatten().collect();
        // Something that only started the tool's programs, which have ended since.
        if said.is_empty() {
            counted(self.processes.len(), "program", "programs").unwrap_or_default()
        } else {
            said.join(" and ")
        }
    }

    /// Lists the programs, for someone at a terminal to end them.
    pub fn programs(&self) -> String {
        let listed = self.processes.iter().map(|process| {
            let program = process.program.as_deref().map_or_else(String::new, |program| program.display().to_string());
            format!("{} {program}", process.id)
        });
        listed.collect::<Vec<_>>().join("\n")
    }
}

/// Whether `parent` started `child`. A process's parent may have ended, and its id gone to a later process.
fn started(parent: &Process, child: &Process) -> bool {
    child.parent == parent.id && parent.id != child.id && parent.started <= child.started
}

fn is_of(program: &Path, tool: &ToolFiles) -> bool {
    // Windows' paths are the same whatever their case.
    let lower = |path: &Path| path.to_string_lossy().to_lowercase();
    let program = lower(program);
    program == lower(&tool.program) || program.starts_with(&format!("{}\\", lower(&tool.environment)))
}

fn is_python(name: &OsStr) -> bool {
    PYTHON.iter().any(|python| name.eq_ignore_ascii_case(python))
}

fn counted(count: usize, one: &str, many: &str) -> Option<String> {
    match count {
        0 => None,
        1 => Some(format!("1 {one}")),
        _ => Some(format!("{count} {many}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ENVIRONMENT: &str = r"C:\Users\me\AppData\Roaming\uv\tools\modeling-3d";
    const PROGRAM: &str = r"C:\Users\me\.local\bin\modeling-3d.exe";
    const BASE_PYTHON: &str = r"C:\Users\me\AppData\Roaming\uv\python\cpython-3.13\python.exe";

    fn tool() -> ToolFiles {
        ToolFiles { environment: PathBuf::from(ENVIRONMENT), program: PathBuf::from(PROGRAM) }
    }

    fn process(id: u32, parent: u32, program: &str, started: u64) -> Process {
        Process { id, parent, program: Some(PathBuf::from(program)), started }
    }

    fn environment(file: &str) -> String {
        format!(r"{ENVIRONMENT}\{file}")
    }

    #[test]
    fn a_session_and_a_run_are_each_counted_once_with_all_they_started() {
        let processes = [
            process(1, 0, r"C:\Program Files\Claude\claude.exe", 1),
            // An agent session's MCP server: the tool's program, its Python, and the Python that one starts.
            process(10, 1, PROGRAM, 10),
            process(11, 10, &environment(r"Scripts\python.exe"), 11),
            process(12, 11, BASE_PYTHON, 12),
            // A detached run, whose first process has ended, and its agent with a command it runs.
            process(20, 99, &environment(r"Scripts\python.exe"), 20),
            process(21, 20, BASE_PYTHON, 21),
            process(22, 21, &environment(r"Lib\site-packages\claude_agent_sdk\_bundled\claude.exe"), 22),
            process(23, 22, r"C:\Users\me\.local\bin\uv.exe", 23),
            process(30, 1, r"C:\Windows\System32\notepad.exe", 30),
        ];
        let in_use = InUse::among(&processes, &tool());
        assert_eq!((in_use.runs, in_use.others), (1, 1));
        let mut stopping: Vec<u32> = in_use.processes.iter().map(|process| process.id).collect();
        stopping.sort_unstable();
        assert_eq!(stopping, [10, 11, 12, 20, 21, 22, 23]);
        assert_eq!(in_use.said(), "1 run and 1 agent session or command");
    }

    #[test]
    fn a_process_that_took_the_id_of_one_that_ended_is_not_its_child() {
        let processes = [process(40, 0, &environment(r"Scripts\python.exe"), 40), process(41, 40, BASE_PYTHON, 5)];
        let in_use = InUse::among(&processes, &tool());
        assert_eq!(in_use.processes.len(), 1);
    }

    #[test]
    fn the_tools_folder_is_told_apart_whatever_the_case() {
        assert!(is_of(Path::new(&environment(r"scripts\PYTHON.exe").to_uppercase()), &tool()));
        assert!(is_of(Path::new(r"c:\users\me\.local\bin\Modeling-3D.exe"), &tool()));
        assert!(!is_of(Path::new(&format!(r"{ENVIRONMENT}-old\Scripts\python.exe")), &tool()));
        assert!(!is_of(Path::new(r"C:\Repos\3d\.venv\Scripts\modeling-3d.exe"), &tool()));
    }

    #[test]
    fn nothing_running_is_nothing_in_use() {
        let in_use = InUse::among(&[process(1, 0, BASE_PYTHON, 1)], &tool());
        assert!(in_use.is_empty());
        let several = InUse { runs: 2, others: 0, processes: Vec::new() };
        assert_eq!(several.said(), "2 runs");
    }
}
