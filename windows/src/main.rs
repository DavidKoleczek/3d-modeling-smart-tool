//! 3D Modeling for Windows: one exe that sets the tool up, runs the app from the tray, and updates and removes them.

// Without this Windows opens a console window beside the exe.
#![windows_subsystem = "windows"]

mod cli;
mod control;
mod failure;
mod in_use;
mod install;
mod instance;
mod node;
mod package;
mod paths;
mod prerequisites;
mod run;
mod server;
mod settings;
mod setup;
mod skill;
mod startup;
mod tool;
mod tray;
mod update;
mod web;
mod win32;

use std::env;
use std::path::Path;
use std::process::ExitCode;

use cli::Command;
use failure::{Failure, OrSay, Outcome};
use in_use::InUse;
use install::{Clearing, Progress};
use package::APP_NAME;
use paths::Paths;
use setup::Purpose;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            eprintln!("{failure}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Outcome<()> {
    let invocation = cli::parse(env::args_os().skip(1))?;
    let paths = Paths::current(invocation.sandbox.as_deref())
        .or_say(|| "The folders to install to couldn't be worked out".to_owned())?;
    match invocation.command {
        Command::Open if install::is_installed(&paths) => tray::run(&paths, true).inspect_err(show),
        Command::Open => setup::run(&paths, Purpose::Install).inspect_err(show),
        Command::Background => tray::run(&paths, false).inspect_err(show),
        Command::Install(options) => {
            let refuse = &mut |in_use: &InUse| Err(install::refuse_in_use(in_use, "replaced"));
            let program = install::install(&options, None, &paths, &mut print, refuse)?;
            print_sign_ins(&program, &paths);
            Ok(())
        }
        Command::Update(adding) => setup::run(&paths, Purpose::Update(adding)).inspect_err(show),
        Command::Uninstall { quiet: true } => {
            install::uninstall(&paths, &mut print, &mut |in_use| Err(install::refuse_in_use(in_use, "removed")))
        }
        Command::Uninstall { quiet: false } => {
            let question = format!(
                "Remove {APP_NAME} and its tool from this computer?\n\nYour workspaces, models, and sign-ins are kept."
            );
            if !win32::ask(APP_NAME, &question) {
                return Ok(());
            }
            install::uninstall(&paths, &mut print, &mut ask_to_stop).inspect_err(show)
        }
    }
}

/// Asks whether to stop what runs from the tool, so it can be removed.
fn ask_to_stop(in_use: &InUse) -> Outcome<Clearing> {
    let question = format!(
        "The tool is in use by {}.\n\nStop them and remove {APP_NAME}? A run that is stopped can be resumed later.",
        in_use.said()
    );
    if win32::ask(APP_NAME, &question) {
        Ok(Clearing::Stop)
    } else {
        Err(Failure::new(format!("{APP_NAME} wasn't removed, since the tool is in use by {}.", in_use.said())))
    }
}

/// Says which agent providers aren't signed in, and where to read how to sign in to them.
fn print_sign_ins(program: &Path, paths: &Paths) {
    match tool::agent_providers(program, paths) {
        Ok(statuses) => {
            let installed = statuses.iter().filter(|status| status.installed);
            for status in installed {
                match &status.signed_in_with {
                    Some(how) => println!("{} is signed in with {how}.", status.agent_provider),
                    None => println!("{} isn't signed in.", status.agent_provider),
                }
            }
            if statuses.iter().any(|status| status.installed && status.signed_in_with.is_none()) {
                println!("How to sign in: {}", package::sign_in_help());
            }
        }
        Err(failure) => println!("Whether the agent providers are signed in couldn't be read. {failure}"),
    }
}

/// Shows what went wrong to someone who started the exe with no terminal to read it in.
fn show(failure: &Failure) {
    win32::show_failure(APP_NAME, &failure.to_string());
}

/// Prints what is going on, which is seen when the exe's output goes to a file or another program.
fn print(progress: Progress) {
    match progress {
        Progress::Started(stage) => println!("{}", stage.label()),
        Progress::Note(note) => println!("{note}"),
    }
}
