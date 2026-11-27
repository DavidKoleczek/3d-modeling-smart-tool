//! What the exe carries, put there by the build.

pub const APP_NAME: &str = env!("APP_NAME");
/// The tool's version, which is the exe's too.
pub const VERSION: &str = env!("APP_VERSION");
pub const PUBLISHER: &str = env!("CARGO_PKG_AUTHORS");
pub const REPOSITORY: &str = env!("APP_REPOSITORY");
pub const WHEEL_NAME: &str = env!("WHEEL_NAME");
pub const WHEEL: &[u8] = include_bytes!(env!("WHEEL_PATH"));
/// The versions of the tool's dependencies it was tested with, every agent provider's among them, as a requirements
/// file.
pub const CONSTRAINTS: &str = include_str!(env!("CONSTRAINTS_PATH"));
/// The Python the tool was tested on.
pub const PYTHON_VERSION: &str = env!("PYTHON_VERSION");
/// The tool's Agent Skill, which tells an agent how to use it.
pub const SKILL: &str = include_str!(env!("SKILL_PATH"));
// The README's part that says what each agent provider needs, signing in among it.
const PREREQUISITES: &str = "#quickstart";

/// Returns where the README says how to sign in to each agent provider.
pub fn sign_in_help() -> String {
    format!("{}{PREREQUISITES}", REPOSITORY.trim_end_matches('/'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_wheel_is_this_version_of_the_tool() {
        assert_eq!(WHEEL_NAME, format!("modeling_3d-{VERSION}-py3-none-any.whl"));
        // A wheel is a zip file, which starts with these bytes.
        assert!(WHEEL.starts_with(b"PK\x03\x04"));
    }

    #[test]
    fn the_dependencies_and_both_agent_providers_are_pinned_and_the_tool_is_not_among_them() {
        for pinned in ["fastapi==", "claude-agent-sdk==", "openai-codex=="] {
            assert!(CONSTRAINTS.lines().any(|line| line.starts_with(pinned)), "{pinned}");
        }
        assert!(CONSTRAINTS.lines().all(|line| line.contains("==")));
        assert!(!CONSTRAINTS.lines().any(|line| line.starts_with("modeling-3d")));
    }

    #[test]
    fn the_skill_is_all_of_its_folder() {
        assert!(SKILL.starts_with("---") && SKILL.contains("name: modeling-3d"));
        let folder = std::path::Path::new(env!("SKILL_PATH")).parent().unwrap();
        // The exe carries the one file, so another beside it would be left out of what is installed.
        assert_eq!(std::fs::read_dir(folder).unwrap().count(), 1);
    }

    #[test]
    fn the_repository_and_python_are_known() {
        assert!(REPOSITORY.starts_with("https://github.com/"));
        assert!(PYTHON_VERSION.starts_with("3."));
        assert!(sign_in_help().starts_with(REPOSITORY) && sign_in_help().ends_with("#quickstart"));
    }
}
