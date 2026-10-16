import pytest
import typer
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.cli import app
from modeling_3d.core import skill as skill_module
from modeling_3d.core.skill import CAPABILITIES
from modeling_3d.schemas import Modeling3dError

RELATIVE_PATHS_LINE = "Relative paths in this skill are relative to the skill directory."
# The tool's skill routes to the capability skills, so it stays a router rather than a manual.
MAXIMUM_BODY_LINES = 120

runner = CliRunner()


def test_manifest_body_is_the_markdown_below_the_frontmatter() -> None:
    body = lib.load_manifest().body

    assert body
    assert not body.startswith("#")


def test_skill_is_a_wrapped_document_naming_every_capability() -> None:
    document = lib.skill()

    assert document.startswith('<skill_content name="modeling-3d">')
    assert document.endswith("</skill_content>")
    assert "# modeling-3d" in document
    assert lib.load_manifest().body in document
    assert "Each has its own skill: `modeling-3d <capability> --help`." in document
    for capability in CAPABILITIES:
        kind = "model-backed" if capability.model_backed else "deterministic"
        assert f"- `{capability.name}` [{kind}] -- {capability.summary}" in document


def test_skill_routes_to_the_capability_skills_instead_of_carrying_them() -> None:
    body = lib.load_manifest().body

    assert len(body.splitlines()) < MAXIMUM_BODY_LINES


def test_repository_line_is_omitted_when_the_package_declares_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_module, "repository_url", lambda: None)
    header = skill_module.skill().splitlines()

    assert "Repository:" not in skill_module.skill()
    assert header[2] == f"Version: {lib.load_manifest().version}"
    assert header[3] == RELATIVE_PATHS_LINE


def test_repository_line_sits_between_the_header_lines_when_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_module, "repository_url", lambda: "https://example.invalid/modeling-3d")
    header = skill_module.skill().splitlines()

    assert header[1].startswith("Skill directory: ")
    assert header[2] == "Repository: https://example.invalid/modeling-3d"
    assert header[3] == f"Version: {lib.load_manifest().version}"
    assert header[4] == RELATIVE_PATHS_LINE


def test_version_line_names_the_manifest_version_in_every_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_module, "repository_url", lambda: None)
    line = f"Version: {lib.load_manifest().version}"

    assert skill_module.skill().splitlines()[2] == line
    for capability in CAPABILITIES:
        assert skill_module.skill(capability.name).splitlines()[2] == line


def test_skill_resources_resolve_under_the_skill_directory() -> None:
    root = skill_module.skill_directory()
    resources = [line.removeprefix("<file>").removesuffix("</file>") for line in _resource_lines(lib.skill())]

    assert resources
    assert resources == skill_module.skill_resources()
    assert (root / "SMART_TOOL.md").is_file()
    for resource in resources:
        assert (root / resource).is_file()


def test_every_capability_ships_the_files_its_skill_names() -> None:
    root = skill_module.skill_directory()

    for capability in CAPABILITIES:
        assert (root / capability.skill).is_file()
        assert skill_module.capability_skill_resources(capability.name) == list(capability.resources)
        for resource in capability.resources:
            assert (root / resource).is_file()


def test_every_capability_skill_is_its_markdown_in_the_tool_s_shape() -> None:
    for capability in CAPABILITIES:
        document = lib.skill(capability.name)
        body = (skill_module.skill_directory() / capability.skill).read_text(encoding="utf-8").strip()
        kind = "Model-backed." if capability.model_backed else "Deterministic."

        assert document.startswith(f'<skill_content name="modeling-3d {capability.name}">')
        assert f"# modeling-3d {capability.name}" in document
        assert kind in document
        assert body in document
        assert document.endswith("</skill_content>")
        if not capability.resources:
            assert "<skill_resources>" not in document


def test_an_unknown_capability_names_the_ones_that_exist() -> None:
    with pytest.raises(Modeling3dError) as failure:
        lib.skill("nope")

    for capability in CAPABILITIES:
        assert capability.name in str(failure.value)


def _resource_lines(document: str) -> list[str]:
    lines = [line.strip() for line in document.splitlines()]
    start = lines.index("<skill_resources>")
    end = lines.index("</skill_resources>")
    return lines[start + 1 : end]


def test_help_prints_the_skill() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert result.stdout.strip() == lib.skill()


def test_short_help_and_no_arguments_print_the_terse_summary() -> None:
    short = runner.invoke(app, ["-h"])
    bare = runner.invoke(app, [])

    assert short.exit_code == 0
    assert "<skill_content" not in short.stdout
    assert "manifest" in short.stdout
    assert "<skill_content" not in bare.stdout


def test_every_command_answers_help_with_its_own_skill() -> None:
    for capability in CAPABILITIES:
        result = runner.invoke(app, [capability.name, "--help"])

        assert result.exit_code == 0
        assert result.stdout.strip() == lib.skill(capability.name)


def test_every_command_answers_short_help_with_the_terse_summary() -> None:
    for capability in CAPABILITIES:
        result = runner.invoke(app, [capability.name, "-h"])

        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        assert "<skill_content" not in result.stdout


def test_the_cli_exposes_exactly_the_capabilities_the_skill_lists() -> None:
    commands = typer.main.get_group(app).commands

    assert set(commands) == {capability.name for capability in CAPABILITIES}


def test_every_capability_skill_documents_every_argument_the_cli_takes() -> None:
    commands = typer.main.get_group(app).commands

    for capability in CAPABILITIES:
        document = lib.skill(capability.name)
        for parameter in commands[capability.name].get_params(typer.Context(commands[capability.name])):
            names = [name for name in parameter.opts if name.startswith("-")]
            if not names:
                assert parameter.name is not None
                assert parameter.name.upper() in document
                continue
            if set(names) <= {"-h", "--help"}:
                continue
            for name in names:
                assert name in document


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_prints_the_distribution_and_its_installed_version(flag: str) -> None:
    result = runner.invoke(app, [flag])

    assert result.exit_code == 0
    assert result.output == f"modeling-3d {lib.version()}\n"
