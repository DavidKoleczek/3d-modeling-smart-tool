//! What went wrong, said for the person at the machine.

use std::fmt::{self, Display};

#[derive(Debug)]
pub struct Failure(String);

pub type Outcome<T> = Result<T, Failure>;

impl Failure {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl Display for Failure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

pub trait OrSay<T> {
    /// Turns an error into a failure that says what couldn't be done, then the error.
    fn or_say(self, what: impl FnOnce() -> String) -> Outcome<T>;
}

impl<T, E: Display> OrSay<T> for Result<T, E> {
    fn or_say(self, what: impl FnOnce() -> String) -> Outcome<T> {
        self.map_err(|error| Failure(format!("{}: {error}", what())))
    }
}
