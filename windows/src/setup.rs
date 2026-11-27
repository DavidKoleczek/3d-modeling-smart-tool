//! Setup: a window that asks what to install, shows the install as it runs, says how the agent providers are signed
//! in, and opens the app at the end. The window holds a page from `ui/`, shown in Windows' web view. An update, and
//! adding an agent provider, are the same window with nothing to ask.

use std::borrow::Cow;
use std::path::PathBuf;
use std::process::Command;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

use serde_json::{Value, json};
use tao::dpi::{LogicalSize, PhysicalPosition};
use tao::event::{Event as LoopEvent, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoop, EventLoopBuilder, EventLoopProxy};
use tao::platform::run_return::EventLoopExtRunReturn;
use tao::platform::windows::{IconExtWindows, WindowExtWindows};
use tao::window::{Icon, Theme, Window, WindowBuilder};
use wry::http::header::CONTENT_TYPE;
use wry::http::{HeaderValue, Response, StatusCode};
use wry::{NewWindowResponse, WebContext, WebView, WebViewBuilder, WebViewBuilderExtWindows};

use crate::failure::{Failure, OrSay, Outcome};
use crate::in_use::InUse;
use crate::install::{self, Clearing, Existing, Options, Progress, Providers, Shortcuts};
use crate::package::{self, APP_NAME, VERSION};
use crate::paths::Paths;
use crate::skill::{Choice, Kit, Mode};
use crate::startup::BACKGROUND;
use crate::tool::{self, ProviderStatus};
use crate::win32;

const TITLE: &str = "3D Modeling Setup";
const SIZE: LogicalSize<f64> = LogicalSize::new(520.0, 600.0);
const UPDATE_TITLE: &str = "3D Modeling Update";
const UPDATE_SIZE: LogicalSize<f64> = LogicalSize::new(520.0, 460.0);
// The page's own name for where it is served from, and what WebView2 makes of it.
const SCHEME: &str = "setup";
const PAGE: &str = "setup://localhost/";
const ORIGIN: &str = "http://setup.localhost/";
// The page's ground in each theme, so the window isn't white while it loads.
const LIGHT_PANEL: (u8, u8, u8, u8) = (0xff, 0xff, 0xff, 0xff);
const DARK_PANEL: (u8, u8, u8, u8) = (0x17, 0x1b, 0x21, 0xff);
// The id winresource gives the exe's icon.
const ICON_RESOURCE: u16 = 1;
const WEBVIEW2: &str = "https://developer.microsoft.com/microsoft-edge/webview2/";
// How many of the workspaces already there the page names.
const WORKSPACES_SHOWN: usize = 3;

/// What the window is opened for.
#[derive(Clone, Copy)]
pub enum Purpose {
    /// Asking what to install, and installing it.
    Install,
    /// Installing this exe over the installed app, as that one was set up and with these agent providers as well as
    /// those it has, and starting the app again.
    Update(Providers),
}

/// What setup is told of: the page from the web view's own callback, and the rest from other threads.
enum Event {
    /// What the page asked, as it sent it.
    Page(String),
    Found(Existing),
    /// Node is being downloaded for the skills CLI, which takes a while.
    Downloading,
    /// The skills CLI, ready, with the agents it lists.
    Agents(Box<Outcome<(Kit, Value)>>),
    /// The tool can't be replaced while this runs from it, which the page is asked about.
    InUse {
        runs: usize,
        others: usize,
        said: String,
    },
    /// The page chose not to wait for what runs from the tool, which left everything as it was.
    Back,
    Progress(Progress),
    /// The install ended, with the tool's program when it worked.
    Installed(Outcome<PathBuf>),
    /// How the agent providers are signed in, as the tool says, with the tool's program that said it.
    Providers(PathBuf, Outcome<Vec<ProviderStatus>>),
}

/// What the page answered about what runs from the tool.
enum Answer {
    Wait,
    Stop,
    Back,
}

struct Setup<'a> {
    paths: &'a Paths,
    purpose: Purpose,
    tell: EventLoopProxy<Event>,
    window: &'a Window,
    page: &'a WebView,
    /// The skills CLI, once it has listed the agents, for installing the skill with.
    kit: Option<Kit>,
    /// Whether the skills CLI is being gotten ready, which one page asking twice doesn't do twice.
    listing: bool,
    installing: bool,
    /// Where the install that is waiting on what runs from the tool hears what the page answered.
    answers: Option<Sender<Answer>>,
    /// The installed tool's program, which says how the agent providers are signed in. It is away while it is asked.
    program: Option<PathBuf>,
    /// Whether the app is to be started again once the window closes, since an update quit it and hasn't started it
    /// yet. Started again as the update left it, it is where to update from again.
    restart_app: bool,
}

/// Shows setup, or an update, and returns once its window is closed.
pub fn run(paths: &Paths, purpose: Purpose) -> Outcome<()> {
    if wry::webview_version().is_err() {
        return match purpose {
            Purpose::Install => offer_web_view(),
            Purpose::Update(adding) => update_unseen(paths, adding),
        };
    }
    let failed = || "Setup's window couldn't be opened".to_owned();
    let mut event_loop = EventLoopBuilder::<Event>::with_user_event().build();
    let window = open_window(&event_loop, purpose).or_say(failed)?;
    let tell = event_loop.create_proxy();
    let from_page = tell.clone();
    // WebView2 otherwise keeps its files beside the exe, which is wherever it was downloaded to.
    let mut context = WebContext::new(Some(paths.local.join("webview")));
    let page = WebViewBuilder::new_with_web_context(&mut context)
        .with_custom_protocol(SCHEME.to_owned(), |_, request| asset(request.uri().path()))
        .with_url(PAGE)
        // The page is answered from the loop and not from here, inside WebView2's own callback, where opening
        // another window would hang it.
        .with_ipc_handler(move |request| drop(from_page.send_event(Event::Page(request.into_body()))))
        .with_navigation_handler(|url| url.starts_with(ORIGIN))
        .with_new_window_req_handler(|_, _| NewWindowResponse::Deny)
        .with_background_color(if window.theme() == Theme::Dark { DARK_PANEL } else { LIGHT_PANEL })
        .with_browser_accelerator_keys(false)
        .with_default_context_menus(false)
        .with_hotkeys_zoom(false)
        .build(&window)
        .or_say(failed)?;
    window.set_visible(true);

    let mut setup = Setup {
        paths,
        purpose,
        tell,
        window: &window,
        page: &page,
        kit: None,
        listing: false,
        installing: false,
        answers: None,
        program: None,
        restart_app: matches!(purpose, Purpose::Update(_)),
    };
    event_loop.run_return(|event, _, flow| {
        let going = match event {
            // Closing it would end an install halfway.
            LoopEvent::WindowEvent { event: WindowEvent::CloseRequested, .. } => setup.installing,
            LoopEvent::UserEvent(event) => setup.handle(event),
            _ => true,
        };
        *flow = if going { ControlFlow::Wait } else { ControlFlow::Exit };
    });
    if setup.restart_app {
        // There is no window left to say it couldn't be.
        let _ = app(paths, true).spawn();
    }
    Ok(())
}

fn offer_web_view() -> Outcome<()> {
    let question = "Setup needs Microsoft Edge WebView2, which this computer doesn't have.\n\n\
                    Open Microsoft's page to download it? Open setup again once it is installed.";
    if win32::ask(APP_NAME, question) {
        win32::open_in_browser(WEBVIEW2).or_say(|| format!("The browser couldn't be opened on {WEBVIEW2}"))?;
    }
    Ok(())
}

/// Updates with no window to show it in, on a computer whose web view has gone since the app was set up, and starts
/// the app again however it went.
fn update_unseen(paths: &Paths, adding: Providers) -> Outcome<()> {
    let updated = Existing::find(paths).kept(adding).and_then(|options| {
        install::install(&options, None, paths, &mut |_| {}, &mut |in_use| {
            let question = format!(
                "The tool is in use by {}, which has to end before it is replaced.\n\nStop them and update \
                 {APP_NAME}? A run that is stopped can be resumed later.",
                in_use.said()
            );
            if win32::ask(APP_NAME, &question) {
                Ok(Clearing::Stop)
            } else {
                Err(Failure::new(format!("{APP_NAME} wasn't updated, since the tool is in use by {}.", in_use.said())))
            }
        })
    });
    let started = app(paths, true).spawn().or_say(|| format!("{APP_NAME} couldn't be started again"));
    updated.and(started).map(drop)
}

/// Returns a command that starts the installed app, in the background or with the browser opened on it.
fn app(paths: &Paths, background: bool) -> Command {
    let mut app = paths.app();
    if background {
        app.arg(BACKGROUND);
    }
    app
}

/// Opens the window in the middle of the main screen, not yet shown.
fn open_window(event_loop: &EventLoop<Event>, purpose: Purpose) -> Result<Window, tao::error::OsError> {
    let (title, size) = match purpose {
        Purpose::Install => (TITLE, SIZE),
        Purpose::Update(_) => (UPDATE_TITLE, UPDATE_SIZE),
    };
    let window = WindowBuilder::new()
        .with_title(title)
        .with_inner_size(size)
        .with_resizable(false)
        .with_maximizable(false)
        .with_window_icon(Icon::from_resource(ICON_RESOURCE, None).ok())
        .with_visible(false)
        .build(event_loop)?;
    if let Some(screen) = window.primary_monitor() {
        let (screen_size, size) = (screen.size(), window.outer_size());
        let middle = |start: i32, around: u32, length: u32| {
            start + (i32::try_from(around).unwrap_or(0) - i32::try_from(length).unwrap_or(0)) / 2
        };
        window.set_outer_position(PhysicalPosition::new(
            middle(screen.position().x, screen_size.width, size.width),
            middle(screen.position().y, screen_size.height, size.height),
        ));
    }
    Ok(window)
}

/// Returns a file of the page, all of which the exe carries.
fn asset(path: &str) -> Response<Cow<'static, [u8]>> {
    let (kind, file): (&str, &[u8]) = match path {
        "/" => ("text/html", include_bytes!("../ui/index.html")),
        "/setup.css" => ("text/css", include_bytes!("../ui/setup.css")),
        "/setup.js" => ("text/javascript", include_bytes!("../ui/setup.js")),
        "/fonts/geist-latin.woff2" => ("font/woff2", include_bytes!("../ui/fonts/geist-latin.woff2")),
        "/fonts/geist-mono-latin.woff2" => ("font/woff2", include_bytes!("../ui/fonts/geist-mono-latin.woff2")),
        _ => {
            let mut missing = Response::new(Cow::Borrowed(&[][..]));
            *missing.status_mut() = StatusCode::NOT_FOUND;
            return missing;
        }
    };
    let mut response = Response::new(Cow::Borrowed(file));
    response.headers_mut().insert(CONTENT_TYPE, HeaderValue::from_static(kind));
    response
}

impl Setup<'_> {
    /// Returns whether setup is to go on.
    fn handle(&mut self, event: Event) -> bool {
        match event {
            Event::Page(message) => return self.asked(&message),
            Event::Found(existing) => match self.purpose {
                Purpose::Install => self.show(&ready(&existing)),
                Purpose::Update(adding) => self.update(existing, adding),
            },
            Event::Downloading => self.show(&json!({ "is": "downloading" })),
            Event::Agents(listed) => {
                self.listing = false;
                match *listed {
                    Ok((kit, agents)) => {
                        self.kit = Some(kit);
                        self.show(&json!({ "is": "agents", "agents": agents }));
                    }
                    Err(failure) => self.show(&json!({ "is": "noAgents", "text": failure.to_string() })),
                }
            }
            Event::InUse { runs, others, said } => {
                // Nothing has been changed yet, so the window can be closed while it waits.
                self.installing = false;
                self.show(&json!({ "is": "inUse", "runs": runs, "others": others, "said": said }));
            }
            Event::Back => {
                self.installing = false;
                self.answers = None;
                match self.purpose {
                    Purpose::Install => self.show(&json!({ "is": "back" })),
                    // Nothing was changed, and the app starts again as it was once the window closes.
                    Purpose::Update(_) => return false,
                }
            }
            Event::Progress(progress) => {
                self.installing = true;
                match progress {
                    Progress::Started(stage) => self.show(&json!({ "is": "started", "label": stage.label() })),
                    Progress::Note(text) => self.show(&json!({ "is": "note", "text": text })),
                }
            }
            Event::Installed(outcome) => {
                self.installing = false;
                self.answers = None;
                match (outcome, self.purpose) {
                    (Err(failure), _) => self.fail(&failure),
                    (Ok(_), Purpose::Update(adding)) if adding == Providers::NONE => {
                        // The app is back by the clock, which is all there is left to show.
                        self.restart_app = !self.start_app(true);
                        return self.restart_app;
                    }
                    (Ok(program), purpose) => {
                        // The browser app that asked for the agent provider loads again once the app is back.
                        if matches!(purpose, Purpose::Update(_)) {
                            self.restart_app = !self.start_app(true);
                        }
                        self.program = Some(program);
                        self.show(&json!({ "is": "installed" }));
                        self.check_providers();
                    }
                }
            }
            Event::Providers(program, outcome) => {
                self.program = Some(program);
                match outcome {
                    Ok(statuses) => self.show(&providers(&statuses)),
                    Err(failure) => self.show(&json!({ "is": "noProviders", "text": failure.to_string() })),
                }
            }
        }
        true
    }

    /// Does what the page asked, and returns whether setup is to go on.
    fn asked(&mut self, message: &str) -> bool {
        let message: Value = serde_json::from_str(message).unwrap_or_default();
        match message["do"].as_str() {
            Some("ready") => {
                let (paths, tell) = (self.paths.clone(), self.tell.clone());
                thread::spawn(move || drop(tell.send_event(Event::Found(Existing::find(&paths)))));
            }
            Some("browse") => {
                match win32::pick_folder(self.window.hwnd(), "Choose a folder for your first workspace") {
                    Ok(Some(folder)) => self.show(&json!({ "is": "folder", "folder": folder })),
                    Ok(None) => {}
                    Err(error) => self.fail(&Failure::new(format!("The folder couldn't be asked for: {error}"))),
                }
            }
            Some("agents") => self.list_agents(),
            Some("install") => self.install(chosen(&message)),
            Some(answer @ ("wait" | "stop" | "back")) => {
                let answer = match answer {
                    "wait" => Answer::Wait,
                    "stop" => Answer::Stop,
                    _ => Answer::Back,
                };
                // The install may have gone on by itself, once what ran from the tool ended.
                if let Some(answers) = &self.answers {
                    let _ = answers.send(answer);
                }
            }
            Some("check") => self.check_providers(),
            Some("signIn") => {
                let help = package::sign_in_help();
                if let Err(error) = win32::open_in_browser(&help) {
                    self.fail(&Failure::new(format!("The browser couldn't be opened on {help}: {error}")));
                }
            }
            Some("open") => return !self.start_app(false),
            Some("close") => return false,
            _ => {}
        }
        true
    }

    /// Starts the installed app, in the background or with the browser opened on it, and returns whether it did.
    fn start_app(&self, background: bool) -> bool {
        let started = app(self.paths, background).spawn();
        if let Err(error) = &started {
            self.fail(&Failure::new(format!("{APP_NAME} couldn't be opened: {error}")));
        }
        started.is_ok()
    }

    /// Gets the skills CLI ready, when it isn't yet, and has it list the agents, from a thread of its own.
    fn list_agents(&mut self) {
        if self.listing {
            return;
        }
        self.listing = true;
        let (kit, paths, tell) = (self.kit.take(), self.paths.clone(), self.tell.clone());
        thread::spawn(move || {
            let downloading = tell.clone();
            let kit =
                kit.map_or_else(|| Kit::prepare(&paths, &mut || drop(downloading.send_event(Event::Downloading))), Ok);
            let listed = kit.and_then(|kit| kit.agents().map(|agents| (kit, agents)));
            drop(tell.send_event(Event::Agents(Box::new(listed))));
        });
    }

    /// Installs over the app as it was set up, with the agent providers in `adding` as well.
    fn update(&mut self, existing: Existing, adding: Providers) {
        let added = (adding != Providers::NONE).then(|| provider_names(adding));
        self.show(&json!({ "is": "updating", "version": VERSION, "installed": existing.version, "adding": added }));
        match existing.kept(adding) {
            Ok(options) => self.install(options),
            Err(failure) => self.fail(&failure),
        }
    }

    fn install(&mut self, options: Options) {
        if let Some(folder) = options.workspace.as_ref().filter(|folder| !folder.is_absolute()) {
            let whole = self.paths.documents.join("3D Models");
            return self.fail(&Failure::new(format!(
                "{} isn't a whole path. Give the workspace's folder from its drive, as in {}.",
                folder.display(),
                whole.display()
            )));
        }
        self.installing = true;
        let (answers, answered) = mpsc::channel();
        self.answers = Some(answers);
        let (kit, paths, tell) = (self.kit.take(), self.paths.clone(), self.tell.clone());
        thread::spawn(move || {
            let mut asking = Asking { tell: tell.clone(), answered, shown: None, waiting: false, backed: false };
            let outcome = install::install(
                &options,
                kit,
                &paths,
                &mut |progress| drop(tell.send_event(Event::Progress(progress))),
                &mut |in_use| asking.clear(in_use),
            );
            drop(tell.send_event(if asking.backed { Event::Back } else { Event::Installed(outcome) }));
        });
    }

    /// Asks the tool how the agent providers are signed in, from a thread of its own.
    fn check_providers(&mut self) {
        // None before the install, and while the tool is already being asked.
        let Some(program) = self.program.take() else {
            return;
        };
        self.show(&json!({ "is": "checking" }));
        let (paths, tell) = (self.paths.clone(), self.tell.clone());
        thread::spawn(move || {
            let statuses = tool::agent_providers(&program, &paths);
            drop(tell.send_event(Event::Providers(program, statuses)));
        });
    }

    fn fail(&self, failure: &Failure) {
        self.show(&json!({ "is": "failed", "text": failure.to_string() }));
    }

    /// Hands the page something to show. JSON is also how JavaScript writes the same value.
    fn show(&self, message: &Value) {
        // A page that can't be told has nothing to show the reason on either.
        let _ = self.page.evaluate_script(&format!("window.setup.show({message})"));
    }
}

/// The install's side of asking the page what to do about what runs from the tool.
struct Asking {
    tell: EventLoopProxy<Event>,
    answered: Receiver<Answer>,
    /// What the page was last shown, so it is told again only of a change.
    shown: Option<(usize, usize)>,
    /// Whether the page chose to wait, so the install looks again by itself until it is told otherwise.
    waiting: bool,
    backed: bool,
}

impl Asking {
    fn clear(&mut self, in_use: &InUse) -> Outcome<Clearing> {
        let counted = (in_use.runs, in_use.others);
        if self.shown != Some(counted) {
            self.shown = Some(counted);
            let (runs, others, said) = (in_use.runs, in_use.others, in_use.said());
            drop(self.tell.send_event(Event::InUse { runs, others, said }));
        }
        let answer = if self.waiting { self.answered.try_recv().ok() } else { self.answered.recv().ok() };
        match answer {
            Some(Answer::Stop) => {
                // Whatever is left once they are stopped, or starts meanwhile, is asked about afresh.
                (self.shown, self.waiting) = (None, false);
                Ok(Clearing::Stop)
            }
            Some(Answer::Wait) => {
                self.waiting = true;
                Ok(Clearing::Wait)
            }
            None if self.waiting => Ok(Clearing::Wait),
            Some(Answer::Back) | None => {
                self.backed = true;
                Err(Failure::new("Setup went back rather than wait for what runs from the tool."))
            }
        }
    }
}

/// Reads what the page says was chosen.
fn chosen(message: &Value) -> Options {
    let chose = |name: &str| message[name].as_bool().unwrap_or(false);
    Options {
        workspace: message["workspace"].as_str().map(str::trim).filter(|folder| !folder.is_empty()).map(PathBuf::from),
        agent_providers: Providers { claude: chose("claude"), codex: chose("codex") },
        shortcuts: Shortcuts { desktop: chose("desktopShortcut"), start_menu: chose("startMenuShortcut") },
        start_at_sign_in: chose("startAtSignIn"),
        skill: chosen_skill(&message["skill"]),
    }
}

/// Reads the skill's choice: the agents and how, false for none, and nothing to leave it as it is.
fn chosen_skill(skill: &Value) -> Choice {
    let agents = skill["agents"].as_array().map(|agents| agents.iter().filter_map(Value::as_str).map(str::to_owned));
    match (skill, agents, skill["mode"].as_str().and_then(Mode::from_name)) {
        (Value::Bool(false), _, _) => Choice::Remove,
        (_, Some(agents), Some(mode)) => Choice::Install { agents: agents.collect(), mode },
        _ => Choice::Keep,
    }
}

fn ready(existing: &Existing) -> Value {
    let options = &existing.options;
    let shown = |folder: &PathBuf| folder.display().to_string();
    json!({
        "is": "ready",
        "version": VERSION,
        "installed": existing.version,
        "workspaces": existing.workspaces.iter().take(WORKSPACES_SHOWN).map(shown).collect::<Vec<_>>(),
        "moreWorkspaces": existing.workspaces.len().saturating_sub(WORKSPACES_SHOWN),
        "workspace": options.workspace.as_ref().map_or_else(String::new, shown),
        "claude": options.agent_providers.claude,
        "codex": options.agent_providers.codex,
        "desktopShortcut": options.shortcuts.desktop,
        "startMenuShortcut": options.shortcuts.start_menu,
        "startAtSignIn": options.start_at_sign_in,
        // On for a first install, and as it was for one before.
        "skill": existing.skill.is_some() || existing.version.is_none(),
        "skillInstalled": existing.skill.is_some(),
        "skillMode": existing.skill.unwrap_or_default().name(),
    })
}

/// The agent providers installed, as the page shows them, with where to read how to sign in to one that isn't.
fn providers(statuses: &[ProviderStatus]) -> Value {
    let installed = statuses.iter().filter(|status| status.installed).map(|status| {
        json!({
            "name": provider_name(&status.agent_provider),
            "signedInWith": status.signed_in_with,
            "problem": status.problem,
        })
    });
    json!({ "is": "providers", "providers": installed.collect::<Vec<_>>() })
}

/// The names of agent providers as a person reads them, as in "Claude and Codex".
fn provider_names(providers: Providers) -> String {
    let names: Vec<String> = providers.extras().split(',').filter(|name| !name.is_empty()).map(provider_name).collect();
    names.join(" and ")
}

/// An agent provider's name as a person reads it.
fn provider_name(agent_provider: &str) -> String {
    match agent_provider {
        "claude" => "Claude".to_owned(),
        "codex" => "Codex".to_owned(),
        other => other.to_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_page_and_everything_it_loads_is_in_the_exe() {
        let page = String::from_utf8_lossy(include_bytes!("../ui/index.html"));
        let styles = String::from_utf8_lossy(include_bytes!("../ui/setup.css"));
        let loaded = page
            .split(['"', '\''])
            .chain(styles.split('"'))
            .filter(|word| [".css", ".js", ".woff2"].iter().any(|kind| word.ends_with(kind)));
        let mut count = 0;
        for file in loaded {
            assert_eq!(asset(&format!("/{file}")).status(), StatusCode::OK, "{file}");
            count += 1;
        }
        assert_eq!(count, 4);
        assert_eq!(asset("/").headers()[CONTENT_TYPE], "text/html");
        assert_eq!(asset("/setup.exe").status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn the_page_is_told_what_is_there_in_its_own_words() {
        let workspaces = ["D:/one", "D:/two", "D:/three", "D:/four"].map(PathBuf::from).to_vec();
        let existing = Existing {
            version: Some("0.4.0".to_owned()),
            workspaces,
            skill: Some(Mode::Copy),
            options: Options {
                agent_providers: Providers { claude: true, codex: false },
                shortcuts: Shortcuts { desktop: false, start_menu: true },
                ..Options::default()
            },
        };
        let told = ready(&existing);
        assert_eq!(told["installed"], "0.4.0");
        assert_eq!(told["workspace"], "");
        assert_eq!(told["workspaces"].as_array().unwrap().len(), 3);
        assert_eq!(told["moreWorkspaces"], 1);
        assert_eq!((&told["claude"], &told["codex"]), (&json!(true), &json!(false)));
        // Every switch the page has is told, by the name the page knows it by.
        let script = include_str!("../ui/setup.js");
        for name in ["claude", "codex", "desktopShortcut", "startMenuShortcut", "startAtSignIn"] {
            assert!(told[name].is_boolean() && script.contains(&format!("{name}: element(")), "{name}");
        }
        assert_eq!((&told["skill"], &told["skillMode"]), (&json!(true), &json!("copy")));
        for name in ["skill", "skillInstalled", "skillMode", "workspaces", "moreWorkspaces"] {
            assert!(script.contains(&format!("found.{name}")), "{name}");
        }
    }

    #[test]
    fn what_the_page_chose_is_read_back() {
        let message = json!({
            "workspace": r" D:\models ", "claude": false, "codex": true, "desktopShortcut": true, "skill": false,
        });
        let options = chosen(&message);
        assert_eq!(options.workspace, Some(PathBuf::from(r"D:\models")));
        assert_eq!(options.agent_providers, Providers { claude: false, codex: true });
        assert_eq!(options.shortcuts, Shortcuts { desktop: true, start_menu: false });
        assert_eq!(options.skill, Choice::Remove);
        assert_eq!(chosen(&json!({ "workspace": "" })).workspace, None);
    }

    #[test]
    fn the_skill_is_installed_for_the_agents_chosen_or_removed_or_left() {
        let chose = |skill: Value| chosen(&json!({ "skill": skill })).skill;
        let agents = vec!["claude-code".to_owned()];
        let install = Choice::Install { agents, mode: Mode::Symlink };
        assert_eq!(chose(json!({ "agents": ["claude-code"], "mode": "symlink" })), install);
        assert_eq!(
            chose(json!({ "agents": [], "mode": "copy" })),
            Choice::Install { agents: vec![], mode: Mode::Copy }
        );
        assert_eq!(chose(json!(false)), Choice::Remove);
        for left in [json!(null), json!(true), json!({ "agents": ["codex"] }), json!({ "mode": "copy" })] {
            assert_eq!(chose(left.clone()), Choice::Keep, "{left}");
        }
    }

    #[test]
    fn the_agent_providers_added_are_named_as_a_person_reads_them() {
        assert_eq!(provider_names(Providers::named("codex").unwrap()), "Codex");
        assert_eq!(provider_names(Providers::default()), "Claude and Codex");
        assert_eq!(provider_names(Providers::NONE), "");
        let script = include_str!("../ui/setup.js");
        assert!(script.contains("updating(") && script.contains("adding"));
    }

    #[test]
    fn only_the_agent_providers_installed_are_shown() {
        let status = |agent_provider: &str, installed: bool, signed_in_with: Option<&str>| ProviderStatus {
            agent_provider: agent_provider.to_owned(),
            installed,
            signed_in_with: signed_in_with.map(str::to_owned),
            problem: signed_in_with.is_none().then(|| "Not signed in.".to_owned()),
        };
        let shown = providers(&[status("claude", true, Some("Claude Max")), status("codex", false, None)]);
        assert_eq!(shown["providers"], json!([{ "name": "Claude", "signedInWith": "Claude Max", "problem": null }]));
        let script = include_str!("../ui/setup.js");
        for name in ["signedInWith", "problem"] {
            assert!(script.contains(name), "{name}");
        }
    }
}
