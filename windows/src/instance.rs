//! One running app per user. The first to start holds two named signals, which a later start raises to have it open
//! the browser, and an install or uninstall to have it quit.

use std::thread;
use std::time::{Duration, Instant};

use crate::failure::{Failure, OrSay, Outcome};
use crate::package::APP_NAME;
use crate::paths::Paths;
use crate::win32::{self, Signal};

const QUIT_PATIENCE: Duration = Duration::from_secs(15);
const QUIT_CHECK: Duration = Duration::from_millis(100);

/// What another process asked of the running app.
#[derive(Clone, Copy, Debug)]
pub enum Asked {
    Open,
    Quit,
}

/// The running app's hold on being the only one.
pub struct Instance {
    open: Signal,
    quit: Signal,
}

impl Instance {
    /// Returns the hold when no app is running. When one is, it is asked to open the browser if `open`, and None is
    /// returned.
    pub fn start(paths: &Paths, open: bool) -> Outcome<Option<Self>> {
        let failed = || "Whether the app is already running couldn't be worked out".to_owned();
        let (open_signal, first) = Signal::create(&name(paths, Asked::Open)).or_say(failed)?;
        if !first {
            if open {
                open_signal.raise().or_say(|| "The running app couldn't be asked to open".to_owned())?;
            }
            return Ok(None);
        }
        let (quit, _) = Signal::create(&name(paths, Asked::Quit)).or_say(failed)?;
        Ok(Some(Self { open: open_signal, quit }))
    }

    /// Tells of everything asked from now on, from a thread of its own, for as long as this process runs.
    pub fn listen(self, tell: impl Fn(Asked) + Send + 'static) {
        thread::spawn(move || {
            while let Ok(raised) = win32::wait_for_any(&[&self.open, &self.quit]) {
                tell(if raised == 0 { Asked::Open } else { Asked::Quit });
            }
        });
    }
}

/// Has the running app quit, and returns once it has. There doesn't have to be one.
pub fn quit_running(paths: &Paths) -> Outcome<()> {
    let started = Instant::now();
    // The signals go when the process that made them does, so this one being gone is the app having ended.
    while Signal::open(&name(paths, Asked::Open)).is_some() {
        if started.elapsed() > QUIT_PATIENCE {
            return Err(Failure::new(format!(
                "{APP_NAME} is still running. Quit it from its icon by the clock, then try again."
            )));
        }
        // Asked on every round, since an app that has only just started hasn't made this one yet.
        if let Some(quit) = Signal::open(&name(paths, Asked::Quit)) {
            quit.raise().or_say(|| "The running app couldn't be asked to quit".to_owned())?;
        }
        thread::sleep(QUIT_CHECK);
    }
    Ok(())
}

fn name(paths: &Paths, asked: Asked) -> String {
    let asked = match asked {
        Asked::Open => "Open",
        Asked::Quit => "Quit",
    };
    // `Local` is this user's session, so another user signed in to the machine has an app of their own.
    format!(r"Local\{}.{asked}", paths.instance())
}
