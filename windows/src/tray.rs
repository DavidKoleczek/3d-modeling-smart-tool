//! The app while it runs: an icon by the clock with a menu, and the server behind it.

use std::io::{self, Write};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant, SystemTime};
use std::{mem, thread};

use tao::event::{Event as LoopEvent, StartCause};
use tao::event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy};
use tao::platform::run_return::EventLoopExtRunReturn;
use tray_icon::menu::{CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem};
use tray_icon::{Icon, MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};

use crate::control::{self, Answer, Control, Reply, Request};
use crate::failure::{Failure, OrSay, Outcome};
use crate::install::Providers;
use crate::instance::{Asked, Instance};
use crate::package::{APP_NAME, VERSION};
use crate::paths::Paths;
use crate::server::{self, Heard, Server};
use crate::settings::Settings;
use crate::skill::{self, Kit, Mode, Record};
use crate::update::{self, Update};
use crate::{startup, tool, win32};

// The ids build.rs gives the exe's icon, and the same icon with the dot that says a newer version is out.
const ICON_RESOURCE: u16 = 1;
const UPDATE_ICON_RESOURCE: u16 = 2;
// A double click is two clicks, and only the first is to open the browser.
const DOUBLE_CLICK: Duration = Duration::from_millis(500);
const CHECK_EVERY: Duration = Duration::from_hours(24);
// A look for a newer version that failed, as one at sign-in can before the network is up, is tried again sooner.
const CHECK_AGAIN_AFTER: Duration = Duration::from_hours(1);
// A sleep doesn't count the time the computer itself is asleep, so the clock is looked at this often instead.
const CLOCK_LOOK: Duration = Duration::from_mins(10);
// The skills CLI is kept ready this long after the agents are listed, for the skill to be installed with.
const KIT_KEPT: Duration = Duration::from_mins(15);
// What installs an agent provider, and is given its name.
const ADD_AGENT_PROVIDER: &str = "--add-agent-provider";

/// The skills CLI, when it is ready, and when it was last used.
type KeptKit = Arc<Mutex<Option<(Kit, Instant)>>>;

/// What the app is told of, each from a thread other than the one it runs on.
enum Event {
    Menu(MenuId),
    Icon(TrayIconEvent),
    Asked(Asked),
    /// What a server told of itself, with which server it was, counted from the first.
    Server {
        started: u32,
        heard: Heard,
    },
    /// What the browser app asked, and where to answer it.
    Control(Request, Answer),
    /// What a look for a newer version found, and who had it made.
    Checked {
        found: Outcome<Option<Update>>,
        looker: Looker,
    },
    /// The user said yes when asked whether to update.
    Update,
    /// An update ended with this app still running, so it didn't take place.
    UpdateEnded(Outcome<()>),
    /// The Agent Skill was installed or removed, as the browser app asked.
    SkillChanged(Outcome<()>, Answer),
}

/// Who had a look for a newer version made, which is who is told what it found.
enum Looker {
    /// Nobody: it was time for one.
    Clock,
    Menu,
    BrowserApp(Answer),
}

enum State {
    Stopped,
    Starting,
    /// Serving the app at this address.
    Listening(String),
}

struct App<'a> {
    paths: &'a Paths,
    proxy: EventLoopProxy<Event>,
    control: Control,
    settings: Settings,
    menu: Menu,
    open: MenuItem,
    sign_in: CheckMenuItem,
    check: MenuItem,
    quit: MenuItem,
    /// The first item of the menu, with the line under it, for as long as there is a newer version.
    update_item: MenuItem,
    update_line: PredefinedMenuItem,
    icon: Option<TrayIcon>,
    server: Option<Server>,
    state: State,
    /// How many servers have been started, which tells the one that is running from those before it.
    started: u32,
    open_when_listening: bool,
    last_click: Option<Instant>,
    /// The newer version there is, as the last look found.
    update: Option<Update>,
    updating: bool,
    kit: KeptKit,
}

/// Runs the app until it is quit, with the browser opened on it first if `open`. When the app is running already,
/// that one is asked to open the browser instead.
pub fn run(paths: &Paths, open: bool) -> Outcome<()> {
    let Some(instance) = Instance::start(paths, open)? else {
        return Ok(());
    };
    let mut event_loop = EventLoopBuilder::<Event>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    // A send only fails once the app has quit, when there is nobody left to tell.
    let tell = proxy.clone();
    MenuEvent::set_event_handler(Some(move |event: MenuEvent| drop(tell.send_event(Event::Menu(event.id)))));
    let tell = proxy.clone();
    TrayIconEvent::set_event_handler(Some(move |event| drop(tell.send_event(Event::Icon(event)))));
    let tell = proxy.clone();
    instance.listen(move |asked| drop(tell.send_event(Event::Asked(asked))));

    let mut app = App::new(paths, proxy, open)?;
    let mut ended = Ok(());
    event_loop.run_return(|event, _, flow| {
        let going = match event {
            // The icon is made once the loop runs, as tray-icon asks.
            LoopEvent::NewEvents(StartCause::Init) => app.begin(),
            LoopEvent::UserEvent(event) => Ok(app.handle(event)),
            _ => Ok(true),
        };
        *flow = match going {
            Ok(true) => ControlFlow::Wait,
            Ok(false) => ControlFlow::Exit,
            Err(failure) => {
                ended = Err(failure);
                ControlFlow::Exit
            }
        };
    });
    app.end();
    ended
}

impl<'a> App<'a> {
    fn new(paths: &'a Paths, proxy: EventLoopProxy<Event>, open: bool) -> Outcome<Self> {
        let open_item = MenuItem::new("Open", true, None);
        let sign_in = CheckMenuItem::new("Start when I sign in", true, startup::is_on(paths), None);
        let check = MenuItem::new("Check for updates", true, None);
        let version = MenuItem::new(format!("Version {VERSION}"), false, None);
        let quit = MenuItem::new("Quit", true, None);
        let menu = Menu::new();
        let (first, second) = (PredefinedMenuItem::separator(), PredefinedMenuItem::separator());
        menu.append_items(&[&open_item, &first, &sign_in, &second, &check, &version, &quit])
            .or_say(|| "The app's menu couldn't be made".to_owned())?;
        let tell = proxy.clone();
        let control = Control::start(move |request, answer| drop(tell.send_event(Event::Control(request, answer))))?;
        Ok(Self {
            paths,
            proxy,
            control,
            settings: Settings::read(paths),
            menu,
            open: open_item,
            sign_in,
            check,
            quit,
            update_item: MenuItem::new("Update", true, None),
            update_line: PredefinedMenuItem::separator(),
            icon: None,
            server: None,
            state: State::Stopped,
            started: 0,
            open_when_listening: open,
            last_click: None,
            update: None,
            updating: false,
            kit: Arc::default(),
        })
    }

    fn begin(&mut self) -> Outcome<bool> {
        let failed = || "The app's icon couldn't be put by the clock".to_owned();
        let icon = TrayIconBuilder::new()
            .with_icon(Icon::from_resource(ICON_RESOURCE, None).or_say(failed)?)
            .with_tooltip(APP_NAME)
            .with_menu(Box::new(self.menu.clone()))
            // A click with the left button opens the app instead.
            .with_menu_on_left_click(false)
            .build()
            .or_say(failed)?;
        self.icon = Some(icon);
        self.start_server();
        self.watch_for_updates();
        Ok(true)
    }

    /// Returns whether the app is to go on.
    fn handle(&mut self, event: Event) -> bool {
        match event {
            Event::Menu(id) if id == *self.open.id() => self.open(),
            Event::Menu(id) if id == *self.sign_in.id() => self.set_start_at_sign_in(self.sign_in.is_checked()),
            Event::Menu(id) if id == *self.check.id() => self.check_for_update(Looker::Menu),
            Event::Menu(id) if id == *self.update_item.id() => self.install_update(),
            Event::Menu(id) if id == *self.quit.id() => return false,
            Event::Icon(TrayIconEvent::Click {
                button: MouseButton::Left, button_state: MouseButtonState::Up, ..
            }) => self.click(),
            // Any other click may be about to show the menu, and the user can have turned starting at sign-in off
            // in Windows since it was last shown.
            Event::Icon(TrayIconEvent::Click { .. }) => self.sign_in.set_checked(startup::is_on(self.paths)),
            Event::Asked(Asked::Open) => self.open(),
            Event::Asked(Asked::Quit) => return false,
            Event::Server { started, heard } if started == self.started => self.heard(heard),
            Event::Control(request, answer) => self.asked_by_browser_app(request, answer),
            Event::Checked { found, looker } => self.checked(found, looker),
            Event::Update => self.install_update(),
            Event::UpdateEnded(outcome) => self.update_ended(outcome),
            // Whoever asked may have stopped waiting.
            Event::SkillChanged(outcome, answer) => drop(answer.send(outcome.map(|()| self.reply()))),
            Event::Menu(_) | Event::Icon(_) | Event::Server { .. } => {}
        }
        true
    }

    fn end(&mut self) {
        if let Some(server) = self.server.take() {
            server.stop();
        }
        // Its folder goes with it, unless it is in use, when the app's next uninstall takes it.
        if let Ok(mut kit) = self.kit.try_lock() {
            kit.take();
        }
        // Windows otherwise shows the icon until the pointer next passes over it.
        self.icon = None;
    }

    fn click(&mut self) {
        let now = Instant::now();
        if self.last_click.is_none_or(|last| now.duration_since(last) > DOUBLE_CLICK) {
            self.open();
        }
        self.last_click = Some(now);
    }

    fn open(&mut self) {
        match &self.state {
            State::Listening(url) => show(url),
            State::Starting => self.open_when_listening = true,
            State::Stopped => {
                self.open_when_listening = true;
                self.start_server();
            }
        }
    }

    /// Does what the browser app asked, and answers it with what the app is like after.
    fn asked_by_browser_app(&mut self, request: Request, answer: Answer) {
        let done = match request {
            Request::State => Ok(()),
            Request::Set { start_at_sign_in } => self.set_from_browser_app(start_at_sign_in),
            Request::CheckForUpdate => return self.check_for_update(Looker::BrowserApp(answer)),
            Request::InstallUpdate if self.update.is_none() => {
                Err(Failure::new("There is no newer version to update to."))
            }
            Request::InstallUpdate => {
                self.install_update();
                Ok(())
            }
            Request::ListAgents => return self.list_agents(answer),
            Request::InstallSkill { agents, mode } => return self.change_skill(Some((agents, mode)), answer),
            Request::RemoveSkill => return self.change_skill(None, answer),
            Request::InstallAgentProvider(adding) => self.install_agent_provider(adding),
        };
        // Whoever asked may have stopped waiting.
        let _ = answer.send(done.map(|()| self.reply()));
    }

    /// Has the skills CLI list the agents, from a thread of its own, and keeps it ready a while for what comes next.
    fn list_agents(&self, answer: Answer) {
        let (kit, paths) = (Arc::clone(&self.kit), self.paths.clone());
        thread::spawn(move || {
            let listed = with_kit(&kit, &paths, Kit::agents);
            drop(answer.send(listed.map(Reply::Agents)));
            thread::sleep(KIT_KEPT);
            let mut kept = kit.lock().unwrap_or_else(PoisonError::into_inner);
            if kept.as_ref().is_some_and(|(_, used)| used.elapsed() >= KIT_KEPT) {
                kept.take();
            }
        });
    }

    /// Installs the Agent Skill for the agents given, or removes it, from a thread of its own.
    fn change_skill(&self, install: Option<(Vec<String>, Mode)>, answer: Answer) {
        let (kit, paths, tell) = (Arc::clone(&self.kit), self.paths.clone(), self.proxy.clone());
        thread::spawn(move || {
            let changed = with_kit(&kit, &paths, |kit| match &install {
                Some((agents, mode)) => kit.install(agents, *mode),
                None => kit.remove(),
            });
            // Nothing needs it until the agents are listed again.
            kit.lock().unwrap_or_else(PoisonError::into_inner).take();
            drop(tell.send_event(Event::SkillChanged(changed, answer)));
        });
    }

    /// Opens the window that installs the tool again with an agent provider added, which quits this app and starts
    /// it again once it is done.
    fn install_agent_provider(&self, adding: Providers) -> Outcome<()> {
        let name = adding.extras();
        let installed = tool::find_uv(self.paths)
            .and_then(|uv| tool::files(&uv, self.paths))
            .ok()
            .and_then(|files| tool::installed_providers(&files));
        if installed.is_some_and(|installed| installed.has(adding)) {
            return Err(Failure::new(format!("The tool has {name} already.")));
        }
        if self.updating {
            return Err(Failure::new("The app is being updated. Try again once it is back."));
        }
        say(&format!("Installing {name}"));
        let mut window = self.paths.app();
        window.args([ADD_AGENT_PROVIDER, &name]);
        window.spawn().map(drop).or_say(|| format!("The window that installs {name} couldn't be opened"))
    }

    fn set_from_browser_app(&mut self, start_at_sign_in: Option<bool>) -> Outcome<()> {
        if let Some(on) = start_at_sign_in {
            let set = startup::set(self.paths, on);
            self.sign_in.set_checked(startup::is_on(self.paths));
            set?;
        }
        Ok(())
    }

    /// What the app is like now, as the browser app is answered.
    fn reply(&self) -> Reply {
        Reply::State(control::State {
            version: VERSION,
            update: self.update.as_ref().map(|update| update.version.clone()),
            updating: self.updating,
            start_at_sign_in: startup::is_on(self.paths),
            skill: Record::read(self.paths).map(|record| control::Skill { agents: record.agents, mode: record.mode }),
        })
    }

    fn set_start_at_sign_in(&mut self, on: bool) {
        if let Err(failure) = startup::set(self.paths, on) {
            report(&failure);
        }
        self.sign_in.set_checked(startup::is_on(self.paths));
    }

    fn start_server(&mut self) {
        self.started += 1;
        match self.start() {
            Ok(server) => {
                self.server = Some(server);
                self.become_state(State::Starting);
            }
            Err(failure) => {
                self.become_state(State::Stopped);
                self.open_when_listening = false;
                report(&failure);
            }
        }
    }

    fn start(&mut self) -> Outcome<Server> {
        let uv = tool::find_uv(self.paths)?;
        let tool = tool::program(&uv, self.paths)?;
        let port = server::free_port(self.settings.port)?;
        if port != self.settings.port {
            self.settings.port = port;
            self.settings.write(self.paths)?;
        }
        let (tell, started) = (self.proxy.clone(), self.started);
        Server::start(&tool, &uv, &self.settings, self.paths, &self.control, move |heard| {
            drop(tell.send_event(Event::Server { started, heard }));
        })
    }

    fn heard(&mut self, heard: Heard) {
        match heard {
            Heard::Listening(url) => {
                say(&format!("Serving {url}"));
                self.forget_first_workspace();
                if mem::take(&mut self.open_when_listening) {
                    show(&url);
                }
                self.become_state(State::Listening(url));
            }
            Heard::Ended(said) => {
                self.server = None;
                // One that ends after it listened is started again by the next Open.
                if matches!(self.state, State::Starting) {
                    self.open_when_listening = false;
                    report(&Failure::new(format!("The app couldn't be started.\n\n{said}")));
                } else {
                    say("The server ended");
                }
                self.become_state(State::Stopped);
            }
        }
    }

    /// Lets go of the workspace setup chose, once a server has opened on it, since the tool remembers it from then on
    /// and opens on whichever was opened last.
    fn forget_first_workspace(&mut self) {
        if self.settings.workspace.is_none() {
            return;
        }
        let settings = Settings { workspace: None, ..self.settings.clone() };
        match settings.write(self.paths) {
            Ok(()) => self.settings = settings,
            Err(failure) => say(&failure.to_string()),
        }
    }

    fn become_state(&mut self, state: State) {
        self.state = state;
        self.show_tooltip();
    }

    /// Says by the icon what a look at it alone doesn't.
    fn show_tooltip(&self) {
        let stopped = matches!(self.state, State::Stopped).then(|| "not running".to_owned());
        let newer = self.update.as_ref().map(|update| format!("version {} is available", update.version));
        let notes: Vec<String> = stopped.into_iter().chain(newer).collect();
        let tooltip = if notes.is_empty() { APP_NAME.to_owned() } else { format!("{APP_NAME} ({})", notes.join(", ")) };
        if let Some(icon) = &self.icon {
            // The tooltip is only a hint, so the app goes on without it.
            let _ = icon.set_tooltip(Some(tooltip));
        }
    }

    /// Looks for a newer version now, and then once a day for as long as the app runs, from a thread of its own.
    fn watch_for_updates(&self) {
        let (paths, tell) = (self.paths.clone(), self.proxy.clone());
        let look = move || {
            let found = update::check(&paths);
            let wait = if found.is_ok() { CHECK_EVERY } else { CHECK_AGAIN_AFTER };
            tell.send_event(Event::Checked { found, looker: Looker::Clock }).ok().map(|()| wait)
        };
        let paths = self.paths.clone();
        thread::spawn(move || {
            let mut wait = look();
            // The exe that updated the app, and then started it, has ended by now.
            update::clear_downloads(&paths);
            skill::clear_leftovers(&paths);
            while let Some(patience) = wait {
                let looked = SystemTime::now();
                // A clock that has been set back is taken as the wait being over.
                while looked.elapsed().is_ok_and(|since| since < patience) {
                    thread::sleep(CLOCK_LOOK);
                }
                wait = look();
            }
        });
    }

    /// Looks for a newer version because the user asked, from the menu or the browser app, which is told what was
    /// found.
    fn check_for_update(&mut self, looker: Looker) {
        // The menu starts one look at a time.
        self.check.set_enabled(false);
        let (paths, tell) = (self.paths.clone(), self.proxy.clone());
        thread::spawn(move || drop(tell.send_event(Event::Checked { found: update::check(&paths), looker })));
    }

    fn checked(&mut self, found: Outcome<Option<Update>>, looker: Looker) {
        // An update that is being installed is past being looked for, and the menu is as that left it.
        let found = found.map(|found| {
            if !self.updating {
                self.offer(found);
            }
        });
        if !self.updating && !matches!(looker, Looker::Clock) {
            self.check.set_enabled(true);
        }
        match (looker, found) {
            // Whoever asked may have stopped waiting.
            (Looker::BrowserApp(answer), found) => drop(answer.send(found.map(|()| self.reply()))),
            (Looker::Menu, Ok(())) if self.updating => {}
            (Looker::Menu, Ok(())) => self.answer(),
            (Looker::Menu, Err(failure)) => report(&failure),
            (Looker::Clock, Ok(())) => {}
            // Nobody asked, so nobody is told, and the next look is sooner.
            (Looker::Clock, Err(failure)) => say(&format!("Updates couldn't be looked for. {failure}")),
        }
    }

    /// Shows that there is a newer version, in the menu and on the icon, or that there no longer is one.
    fn offer(&mut self, update: Option<Update>) {
        if update == self.update {
            return;
        }
        let was_offered = self.update.is_some();
        self.update = update;
        let changed = self.show_update(was_offered);
        if let Err(failure) = changed {
            say(&failure.to_string());
        }
        self.show_tooltip();
    }

    fn show_update(&self, was_offered: bool) -> Outcome<()> {
        let failed = || "The update couldn't be shown".to_owned();
        if let (Some(update), false) = (&self.update, was_offered) {
            say(&format!("Version {} is available", update.version));
            self.menu.prepend_items(&[&self.update_item, &self.update_line]).or_say(failed)?;
        } else if self.update.is_none() {
            self.menu.remove(&self.update_item).or_say(failed)?;
            self.menu.remove(&self.update_line).or_say(failed)?;
        }
        self.name_update_item();
        let resource = if self.update.is_some() { UPDATE_ICON_RESOURCE } else { ICON_RESOURCE };
        if let Some(icon) = &self.icon {
            icon.set_icon(Some(Icon::from_resource(resource, None).or_say(failed)?)).or_say(failed)?;
        }
        Ok(())
    }

    fn name_update_item(&self) {
        if let Some(update) = &self.update {
            let name = if self.updating { "Updating to" } else { "Update to" };
            self.update_item.set_text(format!("{name} {}", update.version));
        }
        self.update_item.set_enabled(!self.updating);
    }

    /// Tells the user what the look they asked for found, from a thread of its own so the icon goes on answering.
    fn answer(&self) {
        let tell = self.proxy.clone();
        if let Some(update) = &self.update {
            let question = format!(
                "Version {} of {APP_NAME} is available. This is version {VERSION}.\n\nUpdate now?",
                update.version
            );
            thread::spawn(move || {
                if win32::ask(APP_NAME, &question) {
                    drop(tell.send_event(Event::Update));
                }
            });
        } else {
            let note = format!("This is the newest version of {APP_NAME}, {VERSION}.");
            say(&note);
            thread::spawn(move || win32::show_note(APP_NAME, &note));
        }
    }

    /// Downloads the newer version and has it take this app's place, from a thread of its own.
    fn install_update(&mut self) {
        let Some(update) = self.update.clone().filter(|_| !self.updating) else {
            return;
        };
        say(&format!("Updating to {}", update.version));
        self.set_updating(true);
        let (paths, tell) = (self.paths.clone(), self.proxy.clone());
        thread::spawn(move || drop(tell.send_event(Event::UpdateEnded(update.install(&paths)))));
    }

    fn update_ended(&mut self, outcome: Outcome<()>) {
        self.set_updating(false);
        if let Err(failure) = outcome {
            report(&Failure::new(format!("The update wasn't installed.\n\n{failure}")));
        }
    }

    fn set_updating(&mut self, updating: bool) {
        self.updating = updating;
        self.check.set_enabled(!updating);
        self.name_update_item();
    }
}

/// Runs something with the skills CLI, which is gotten ready first when it isn't. One thing runs with it at a time.
fn with_kit<T>(kit: &Mutex<Option<(Kit, Instant)>>, paths: &Paths, run: impl FnOnce(&Kit) -> Outcome<T>) -> Outcome<T> {
    let mut kept = kit.lock().unwrap_or_else(PoisonError::into_inner);
    let ready = match kept.take() {
        Some((ready, _)) => ready,
        None => Kit::prepare(paths, &mut || {})?,
    };
    let done = run(&ready);
    *kept = Some((ready, Instant::now()));
    done
}

fn show(url: &str) {
    say(&format!("Opening {url}"));
    if let Err(error) = win32::open_in_browser(url) {
        report(&Failure::new(format!("The browser couldn't be opened on {url}: {error}")));
    }
}

/// Shows what went wrong in a window of its own, from a thread of its own so the icon and its menu go on answering.
fn report(failure: &Failure) {
    let text = failure.to_string();
    say(&text);
    thread::spawn(move || win32::show_failure(APP_NAME, &text));
}

/// Prints what the app is doing, which is seen when the exe's output goes to a file or another program. Nothing may
/// be reading by now, which isn't a reason to stop.
fn say(what: &str) {
    let _ = writeln!(io::stdout(), "{what}");
}
