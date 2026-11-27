//! Starting the app when the user signs in, which is a value under the `Run` key of their part of the registry.

use windows::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows_registry::CURRENT_USER;

use crate::failure::{OrSay, Outcome};
use crate::paths::Paths;

const VALUE: &str = "Modeling3D";
/// The argument Windows starts the app with, which keeps it from opening the browser at every sign-in.
pub const BACKGROUND: &str = "--background";

/// Returns whether Windows starts the app at sign-in, which the user can also turn off in Task Manager and Settings.
pub fn is_on(paths: &Paths) -> bool {
    let listed = CURRENT_USER.open(paths.run_key()).and_then(|key| key.get_string(VALUE)).is_ok();
    // Windows leaves the value under `Run` when a startup app is turned off, and notes it here instead.
    let noted = CURRENT_USER.open(paths.startup_approved_key()).and_then(|key| key.get_value(VALUE));
    listed && !noted.is_ok_and(|note| !is_approved(&note))
}

pub fn set(paths: &Paths, on: bool) -> Outcome<()> {
    let failed = || "Starting at sign-in couldn't be changed".to_owned();
    if on {
        let command = paths.app_text(BACKGROUND);
        CURRENT_USER.create(paths.run_key()).and_then(|key| key.set_string(VALUE, command)).or_say(failed)?;
    } else {
        remove_value(&paths.run_key()).or_say(failed)?;
    }
    // Without a note the app is on when it is listed, so turning it on here undoes a turning off elsewhere.
    remove_value(&paths.startup_approved_key()).or_say(failed)
}

/// Whether a note Windows keeps about a startup app says it is on, which is when its first byte is even.
fn is_approved(note: &[u8]) -> bool {
    note.first().is_none_or(|state| state % 2 == 0)
}

/// Removes the app's value from a key. Neither the key nor the value has to be there.
fn remove_value(key: &str) -> windows_registry::Result<()> {
    let removed = CURRENT_USER.options().read().write().open(key).and_then(|key| key.remove_value(VALUE));
    match removed {
        Err(error) if error.code() != ERROR_FILE_NOT_FOUND.to_hresult() => Err(error),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_startup_app_is_on_unless_windows_notes_it_off() {
        let on = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
        let off = [3, 0, 0, 0, 0x5a, 0x1c, 0x9e, 0x44, 0x2b, 0x1a, 0xdc, 0x01];
        assert!(is_approved(&on));
        assert!(!is_approved(&off));
        assert!(is_approved(&[6, 0, 0, 0]));
        assert!(!is_approved(&[7, 0, 0, 0]));
        assert!(is_approved(&[]));
    }
}
