"""Skill: what the tool tells an agent that has decided to drive it."""

from importlib.metadata import metadata
from importlib.metadata import version as distribution_version
from pathlib import Path

from modeling_3d.core.manifest import MANIFEST_PATH, load_manifest
from modeling_3d.schemas import Capability, Modeling3dError

DISTRIBUTION = "modeling-3d"

# One table drives the skill's capability list, so it cannot drift from what the CLI exposes.
# Every capability added to the library gets a row here, naming the capability's own skill:
# the Markdown beside its code, at `capabilities/<name>/SKILL.md`.
CAPABILITIES = (
    Capability("manifest", "Print the tool's manifest as JSON.", model_backed=False, skill="core/manifest.md"),
    Capability(
        "app",
        "Serve the app, a chat page on this machine, without an agent session; print its URL.",
        model_backed=False,
        skill="capabilities/app/SKILL.md",
    ),
    Capability(
        "mcp",
        "Serve the app to Claude Code over stdio as a channel, so the person and the session talk through it.",
        model_backed=False,
        skill="adapters/mcp.md",
    ),
)

# Paths relative to the skill directory. Both ship inside the package, so both resolve after installation.
SKILL_RESOURCES = ("SMART_TOOL.md", "lib.py")


def skill_directory() -> Path:
    """The installed package root, resolved at runtime, where the tool's own files live."""
    return MANIFEST_PATH.parent.resolve()


def version() -> str:
    """The installed package's version, from its metadata."""
    return distribution_version(DISTRIBUTION)


def repository_url() -> str | None:
    """The tool's canonical source, from the package metadata, or None when the package declares none."""
    for entry in metadata(DISTRIBUTION).get_all("Project-URL") or []:
        label, _, url = str(entry).partition(",")
        if label.strip().lower() == "repository":
            return url.strip()
    return None


def capability(name: str) -> Capability:
    """The capability that answers to `name`, as the skill and the CLI both present it."""
    for entry in CAPABILITIES:
        if entry.name == name:
            return entry
    known = ", ".join(entry.name for entry in CAPABILITIES)
    raise Modeling3dError(f"'{name}' is not a capability of this tool. The capabilities are: {known}.")


def skill_resources() -> list[str]:
    """The files the skill lists, as paths relative to the skill directory."""
    return _installed(SKILL_RESOURCES)


def capability_skill_resources(name: str) -> list[str]:
    """The files a capability's skill lists, as paths relative to the skill directory."""
    return _installed(capability(name).resources)


def skill(capability: str | None = None) -> str:
    """The tool's skill, or one capability's skill when named."""
    if capability is None:
        return _tool_skill()
    return _capability_skill(capability)


def _tool_skill() -> str:
    """The tool's skill: the manifest body, the capability list, and where the tool's files are."""
    manifest = load_manifest()
    body = [
        manifest.body,
        "",
        "## Capabilities",
        "",
        f"Each has its own skill: `{manifest.name} <capability> --help`.",
        "",
    ]
    for entry in CAPABILITIES:
        kind = "model-backed" if entry.model_backed else "deterministic"
        body.append(f"- `{entry.name}` [{kind}] -- {entry.summary}")
    return _document(manifest.name, [], manifest.name, body, skill_resources())


def _capability_skill(name: str) -> str:
    """One capability's skill: the same shape as the tool's, scoped to what it takes, returns, and fails on."""
    entry = capability(name)
    tool = load_manifest().name
    # The body and the resources are checked together, so neither can name a file the package does not ship.
    body_path, *resources = _installed((entry.skill, *entry.resources))
    kind = "Model-backed." if entry.model_backed else "Deterministic."
    body = [kind, "", (skill_directory() / body_path).read_text(encoding="utf-8").strip()]
    return _document(
        f"{tool} {entry.name}",
        [f"Part of `{tool}`; `{tool} --help` is the tool's skill."],
        f"{tool} {entry.name}",
        body,
        resources,
    )


def _document(name: str, header: list[str], heading: str, body: list[str], resources: list[str]) -> str:
    """Render one skill, so the tool's and a capability's cannot drift apart in shape."""
    repository = repository_url()
    lines = [f'<skill_content name="{name}">', f"Skill directory: {skill_directory()}"]
    # A caller that can run the tool cannot always read its files, so the canonical source stands in for them.
    if repository:
        lines.append(f"Repository: {repository}")
    lines.append(f"Version: {version()}")
    lines.append("Relative paths in this skill are relative to the skill directory.")
    lines += header
    lines += ["", f"# {heading}", "", *body]
    if resources:
        lines += ["", "<skill_resources>"]
        lines += [f"  <file>{path}</file>" for path in resources]
        lines.append("</skill_resources>")
    lines.append("</skill_content>")
    return "\n".join(lines)


def _installed(paths: tuple[str, ...]) -> list[str]:
    """The given paths, checked against the installed package so a skill can never name a file that is not there."""
    root = skill_directory()
    missing = [path for path in paths if not (root / path).is_file()]
    if missing:
        raise Modeling3dError(
            f"The skill names files that are not in the installed package: {', '.join(missing)}. "
            f"Ship them under {root} or drop them from the skill."
        )
    return list(paths)
