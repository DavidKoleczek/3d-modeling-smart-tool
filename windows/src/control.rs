//! How the browser app reaches this one, for the settings that are this app's to keep, for updating it, and for
//! adding an agent provider. The app listens on a port of this machine's own address, and tells the server it starts
//! the port and a token. The server asks in one line of JSON that has the token, and is answered in one line.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::Duration;

use serde_json::{Value, json};

use crate::failure::{Failure, OrSay, Outcome};
use crate::install::Providers;
use crate::skill::Mode;
use crate::win32;

/// The variables the server is told the port and the token in.
const PORT_VARIABLE: &str = "MODELING_3D_WINDOWS_APP_PORT";
const TOKEN_VARIABLE: &str = "MODELING_3D_WINDOWS_APP_TOKEN";
const TOKEN_BYTES: usize = 32;
// Far past the longest request there is.
const REQUEST_LIMIT: u64 = 4096;
const REQUEST_PATIENCE: Duration = Duration::from_secs(5);
// Getting the skills CLI ready, which can mean downloading Node, is the longest thing asked.
const ANSWER_PATIENCE: Duration = Duration::from_mins(5);

/// What the browser app asks.
#[derive(Clone, Debug, PartialEq)]
pub enum Request {
    State,
    /// Change the settings that are given, and leave the others.
    Set {
        start_at_sign_in: Option<bool>,
    },
    CheckForUpdate,
    InstallUpdate,
    /// List the agents the Agent Skill can be installed for.
    ListAgents,
    /// Install the Agent Skill in the shared folder and for these agents, and take it from the others.
    InstallSkill {
        agents: Vec<String>,
        mode: Mode,
    },
    RemoveSkill,
    /// Install the tool again with this agent provider as well as the one it has.
    InstallAgentProvider(Providers),
}

/// What the app is like now, as the browser app shows it.
#[derive(Debug)]
pub struct State {
    pub version: &'static str,
    /// The newer version there is to update to.
    pub update: Option<String>,
    pub updating: bool,
    pub start_at_sign_in: bool,
    pub skill: Option<Skill>,
}

/// The Agent Skill, when it is installed.
#[derive(Debug)]
pub struct Skill {
    /// The agents it is for, as the skills CLI names them.
    pub agents: Vec<String>,
    pub mode: Mode,
}

/// What a request is answered with.
#[derive(Debug)]
pub enum Reply {
    /// What the app is like once it has done what was asked.
    State(State),
    /// The agents, as the skills CLI lists them.
    Agents(Value),
}

/// Where a request is answered: with its reply, or why it couldn't be done.
pub type Answer = Sender<Outcome<Reply>>;

/// The app's ear for the browser app, which listens for as long as this exe runs.
pub struct Control {
    port: u16,
    token: String,
}

impl Control {
    /// Starts listening. `ask` is handed each request with where to answer it, from a thread of the request's own.
    pub fn start(ask: impl Fn(Request, Answer) + Clone + Send + 'static) -> Outcome<Self> {
        let failed = || "The app couldn't listen for the browser app".to_owned();
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).or_say(failed)?;
        let port = listener.local_addr().or_say(failed)?.port();
        let token = win32::random_bytes::<TOKEN_BYTES>().or_say(failed)?;
        let token = token.iter().fold(String::new(), |hex, byte| format!("{hex}{byte:02x}"));
        let expected = token.clone();
        thread::spawn(move || {
            for connection in listener.incoming().flatten() {
                let (ask, expected) = (ask.clone(), expected.clone());
                thread::spawn(move || serve(&connection, &expected, &ask));
            }
        });
        Ok(Self { port, token })
    }

    /// Returns the variables that tell the server where the app listens and what to say to be heard.
    pub fn environment(&self) -> [(&'static str, String); 2] {
        [(PORT_VARIABLE, self.port.to_string()), (TOKEN_VARIABLE, self.token.clone())]
    }
}

fn serve(mut connection: &TcpStream, token: &str, ask: &impl Fn(Request, Answer)) {
    // A connection that says nothing isn't waited on for long.
    let _ = connection.set_read_timeout(Some(REQUEST_PATIENCE));
    let mut line = String::new();
    let outcome = BufReader::new(connection.take(REQUEST_LIMIT))
        .read_line(&mut line)
        .or_say(|| "The request couldn't be read".to_owned())
        .and_then(|_| parse(&line, token))
        .and_then(|request| {
            let (answer, answered) = mpsc::channel();
            ask(request, answer);
            // Nothing comes when the app is quitting.
            answered.recv_timeout(ANSWER_PATIENCE).unwrap_or_else(|_| Err(Failure::new("The app didn't answer.")))
        });
    // Whoever asked may be gone, which is theirs to notice.
    let _ = writeln!(connection, "{}", to_json(&outcome));
}

fn parse(line: &str, token: &str) -> Outcome<Request> {
    let asked: Value = serde_json::from_str(line).unwrap_or_default();
    if !asked["token"].as_str().is_some_and(|given| is_same(given, token)) {
        return Err(Failure::new("Only the server this app started can ask it."));
    }
    match asked["do"].as_str() {
        Some("state") => Ok(Request::State),
        Some("set") => Ok(Request::Set { start_at_sign_in: asked["start_at_sign_in"].as_bool() }),
        Some("check_for_update") => Ok(Request::CheckForUpdate),
        Some("install_update") => Ok(Request::InstallUpdate),
        Some("list_agents") => Ok(Request::ListAgents),
        Some("install_skill") => {
            let agents: Option<Vec<String>> = asked["agents"]
                .as_array()
                .map(|agents| agents.iter().filter_map(Value::as_str).map(str::to_owned).collect());
            match (agents, asked["mode"].as_str().and_then(Mode::from_name)) {
                (Some(agents), Some(mode)) => Ok(Request::InstallSkill { agents, mode }),
                _ => Err(Failure::new("install_skill takes the agents, and a mode of symlink or copy.")),
            }
        }
        Some("remove_skill") => Ok(Request::RemoveSkill),
        Some("install_agent_provider") => asked["agent_provider"]
            .as_str()
            .and_then(Providers::named)
            .map(Request::InstallAgentProvider)
            .ok_or_else(|| Failure::new("install_agent_provider takes an agent_provider of claude or codex.")),
        _ => Err(Failure::new(
            "The app can be asked: state, set, check_for_update, install_update, list_agents, install_skill, \
             remove_skill, install_agent_provider.",
        )),
    }
}

/// Whether two tokens are the same, in a time that doesn't tell how much of a wrong one was right.
fn is_same(given: &str, token: &str) -> bool {
    given.len() == token.len()
        && given.bytes().zip(token.bytes()).fold(0, |differing, (one, other)| differing | (one ^ other)) == 0
}

fn to_json(outcome: &Outcome<Reply>) -> Value {
    match outcome {
        Ok(Reply::State(state)) => json!({
            "ok": true,
            "state": {
                "version": state.version,
                "update": state.update,
                "updating": state.updating,
                "start_at_sign_in": state.start_at_sign_in,
                "skill": state.skill.as_ref().map(|skill| json!({ "agents": skill.agents, "mode": skill.mode.name() })),
            },
        }),
        Ok(Reply::Agents(agents)) => json!({ "ok": true, "agents": agents }),
        Err(failure) => json!({ "ok": false, "error": failure.to_string() }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TOKEN: &str = "0f1e2d3c";

    fn asked(line: &str) -> Outcome<Request> {
        parse(line, TOKEN)
    }

    #[test]
    fn a_request_is_read_from_its_line() {
        assert_eq!(asked(r#"{"token": "0f1e2d3c", "do": "state"}"#).unwrap(), Request::State);
        let set = asked(r#"{"token": "0f1e2d3c", "do": "set", "start_at_sign_in": true}"#).unwrap();
        assert_eq!(set, Request::Set { start_at_sign_in: Some(true) });
        let set = asked(r#"{"token": "0f1e2d3c", "do": "set", "start_at_sign_in": null}"#).unwrap();
        assert_eq!(set, Request::Set { start_at_sign_in: None });
        assert_eq!(asked(r#"{"token": "0f1e2d3c", "do": "check_for_update"}"#).unwrap(), Request::CheckForUpdate);
        assert_eq!(asked(r#"{"token": "0f1e2d3c", "do": "install_update"}"#).unwrap(), Request::InstallUpdate);
        assert_eq!(asked(r#"{"token": "0f1e2d3c", "do": "list_agents"}"#).unwrap(), Request::ListAgents);
        let install =
            asked(r#"{"token": "0f1e2d3c", "do": "install_skill", "agents": ["claude-code"], "mode": "copy"}"#);
        assert_eq!(
            install.unwrap(),
            Request::InstallSkill { agents: vec!["claude-code".to_owned()], mode: Mode::Copy }
        );
        assert_eq!(asked(r#"{"token": "0f1e2d3c", "do": "remove_skill"}"#).unwrap(), Request::RemoveSkill);
        let codex = asked(r#"{"token": "0f1e2d3c", "do": "install_agent_provider", "agent_provider": "codex"}"#);
        assert_eq!(codex.unwrap(), Request::InstallAgentProvider(Providers { claude: false, codex: true }));
    }

    #[test]
    fn installing_the_skill_needs_its_agents_and_how() {
        for line in [
            r#"{"token": "0f1e2d3c", "do": "install_skill", "agents": ["codex"]}"#,
            r#"{"token": "0f1e2d3c", "do": "install_skill", "mode": "symlink"}"#,
            r#"{"token": "0f1e2d3c", "do": "install_skill", "agents": [], "mode": "hardlink"}"#,
        ] {
            assert!(asked(line).unwrap_err().to_string().contains("install_skill takes"), "{line}");
        }
    }

    #[test]
    fn installing_an_agent_provider_needs_one_there_is() {
        for line in [
            r#"{"token": "0f1e2d3c", "do": "install_agent_provider"}"#,
            r#"{"token": "0f1e2d3c", "do": "install_agent_provider", "agent_provider": "copilot"}"#,
            r#"{"token": "0f1e2d3c", "do": "install_agent_provider", "agent_provider": "claude,codex"}"#,
        ] {
            assert!(asked(line).unwrap_err().to_string().contains("claude or codex"), "{line}");
        }
    }

    #[test]
    fn a_request_without_the_token_is_refused() {
        for line in [
            r#"{"do": "state"}"#,
            r#"{"token": "0f1e2d3d", "do": "state"}"#,
            r#"{"token": "0f1e2d3c0", "do": "state"}"#,
            r#"{"token": "", "do": "state"}"#,
            r#"{"token": 5, "do": "state"}"#,
            "GET / HTTP/1.1",
            "",
        ] {
            assert!(asked(line).unwrap_err().to_string().contains("Only the server"), "{line}");
        }
    }

    #[test]
    fn a_request_for_something_else_is_told_what_there_is() {
        let failure = asked(r#"{"token": "0f1e2d3c", "do": "quit"}"#).unwrap_err().to_string();
        assert!(failure.contains("check_for_update") && failure.contains("install_agent_provider"), "{failure}");
    }

    #[test]
    fn an_answer_is_the_state_or_why_not() {
        let state = State {
            version: "0.5.0",
            update: Some("0.6.0".to_owned()),
            updating: false,
            start_at_sign_in: true,
            skill: Some(Skill { agents: vec!["Claude Code".to_owned()], mode: Mode::Symlink }),
        };
        let answer = to_json(&Ok(Reply::State(state)));
        assert_eq!(answer["ok"], true);
        assert_eq!(answer["state"]["update"], "0.6.0");
        assert_eq!((&answer["state"]["updating"], &answer["state"]["start_at_sign_in"]), (&json!(false), &json!(true)));
        assert_eq!(answer["state"]["skill"], json!({ "agents": ["Claude Code"], "mode": "symlink" }));
        let answer = to_json(&Ok(Reply::Agents(json!({ "agents": [] }))));
        assert_eq!(answer, json!({ "ok": true, "agents": { "agents": [] } }));
        let answer = to_json(&Err(Failure::new("There is no newer version.")));
        assert_eq!(answer, json!({ "ok": false, "error": "There is no newer version." }));
        // One line, which is where whoever asked stops reading.
        assert!(!answer.to_string().contains('\n'));
    }

    #[test]
    fn the_server_is_answered_over_the_port_it_is_told() {
        let control = Control::start(|request, answer| {
            let start_at_sign_in = matches!(request, Request::Set { start_at_sign_in: Some(true) });
            let state = State { version: "0.5.0", update: None, updating: false, start_at_sign_in, skill: None };
            answer.send(Ok(Reply::State(state))).unwrap();
        })
        .unwrap();
        let [(_, port), (_, token)] = control.environment();
        let ask = |line: String| {
            let mut connection = TcpStream::connect((Ipv4Addr::LOCALHOST, port.parse().unwrap())).unwrap();
            writeln!(connection, "{line}").unwrap();
            let mut answer = String::new();
            BufReader::new(connection).read_line(&mut answer).unwrap();
            serde_json::from_str::<Value>(&answer).unwrap()
        };
        let answer = ask(json!({ "token": token, "do": "set", "start_at_sign_in": true }).to_string());
        assert_eq!((&answer["ok"], &answer["state"]["start_at_sign_in"]), (&json!(true), &json!(true)));
        assert_eq!(ask(json!({ "token": "wrong", "do": "state" }).to_string())["ok"], false);
    }
}
