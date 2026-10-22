"""Lists and views models whose model.json is written directly, so no agent is needed."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.cli import app
from modeling_3d.schemas import (
    AgentProvider,
    Modeling3dError,
    ModelListing,
    ModelRecord,
    ModelRunRecord,
    ModelRunStatus,
    ModelSummary,
)

START = datetime(2026, 10, 17, 10, tzinfo=UTC)
# Above Linux's highest pid and never handed out on Windows, so no process has it.
GONE_PID = 2**22 + 7

runner = CliRunner()


@pytest.fixture(autouse=True)
def working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_model(
    name: str,
    minutes: int | None = 0,
    status: ModelRunStatus = "done",
    pid: int = 1234,
    root: Path = Path(".modeling-3d"),
) -> Path:
    """A model whose one run started `minutes` after START and sent its last event a minute later; None never ran."""
    target = root / name
    target.mkdir(parents=True)
    runs = []
    if minutes is not None:
        started = START + timedelta(minutes=minutes)
        runs.append(
            ModelRunRecord(
                id=f"run-{name}",
                prompt=f"A {name}",
                resumed=False,
                agent_provider="claude",
                model="claude-sonnet-5-5",
                reasoning_effort="medium",
                session_id=f"session-{name}",
                status=status,
                pid=pid,
                started=started,
                last_event=started + timedelta(minutes=1),
            )
        )
        (target / "model.py").write_text("# the model", encoding="utf-8")
        (target / "model.glb").write_bytes(b"glTF")
    record = ModelRecord(id=f"id-{name}", name=name, created=START - timedelta(days=1), runs=runs)
    (target / "model.json").write_text(record.model_dump_json(), encoding="utf-8")
    return target


@pytest.mark.parametrize("exists", [False, True], ids=["missing", "empty"])
def test_a_missing_or_empty_directory_lists_no_models(working_directory: Path, exists: bool) -> None:
    if exists:
        (working_directory / ".modeling-3d").mkdir()

    listing = lib.list_3d_models()

    assert listing == ModelListing(
        directory=working_directory / ".modeling-3d", models=[], last_viewed=None, unreadable=[]
    )


def test_a_file_in_place_of_the_directory_names_the_fix(working_directory: Path) -> None:
    (working_directory / "models").write_text("", encoding="utf-8")

    with pytest.raises(Modeling3dError) as failure:
        lib.list_3d_models(Path("models"))

    assert "is a file, not a directory of models" in str(failure.value)
    assert "--directory" in str(failure.value)


def test_models_list_newest_first_with_their_files_and_folders_without_a_record_are_skipped(
    working_directory: Path,
) -> None:
    bear = make_model("bear", minutes=0)
    make_model("fox", minutes=30)
    make_model("elk", minutes=30)
    make_model("owl", minutes=None)
    (bear / "renders").mkdir()
    (bear / "renders" / "side.png").write_bytes(b"png")
    (bear / "renders" / "front.png").write_bytes(b"png")
    (working_directory / ".modeling-3d" / "notes").mkdir()

    listing = lib.list_3d_models()

    assert [model.name for model in listing.models] == ["elk", "fox", "bear", "owl"]
    first, *_, owl = listing.models
    assert first.directory == working_directory / ".modeling-3d" / "elk"
    assert first.updated == START + timedelta(minutes=31)
    assert first.status == "done"
    assert first.last_run is not None
    assert (first.last_run.prompt, first.last_run.session_id) == ("A elk", "session-elk")
    assert (first.last_session, first.resumable) == (first.last_run, True)
    assert listing.models[2].files == ["model.py", "model.glb", "renders/front.png", "renders/side.png"]
    assert (owl.status, owl.last_run, owl.last_session, owl.resumable, owl.files, owl.updated) == (
        None,
        None,
        None,
        False,
        [],
        owl.created,
    )
    assert listing.unreadable == []


@pytest.mark.parametrize(
    ("agent_provider", "rollout", "resumable"),
    [
        ("claude", None, True),
        ("codex", None, False),
        ("codex", "sessions/2026/10/17/rollout-2026-10-17T10-00-00-{}.jsonl", True),
        ("codex", "archived_sessions/rollout-2026-10-17T10-00-00-{}_0199f1c2-rollout.jsonl.zst", True),
    ],
    ids=["claude", "codex-elsewhere", "codex-here", "codex-archived"],
)
def test_a_follow_up_continues_the_latest_session_where_its_agent_provider_still_keeps_it(
    codex_home: Path, agent_provider: AgentProvider, rollout: str | None, resumable: bool
) -> None:
    bear = make_model("bear")
    record = ModelRecord.model_validate_json((bear / "model.json").read_text(encoding="utf-8"))
    session = record.runs[0].model_copy(update={"agent_provider": agent_provider, "session_id": "0199f1c2-thread"})
    unstarted = session.model_copy(update={"id": "run-unstarted", "session_id": None, "status": "failed"})
    record.runs = [session, unstarted]
    (bear / "model.json").write_text(record.model_dump_json(), encoding="utf-8")
    if rollout is not None:
        path = codex_home / rollout.format(session.session_id)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")

    summary = lib.view_3d_model("bear")

    assert (summary.last_run, summary.last_session, summary.resumable) == (unstarted, session, resumable)


def test_built_is_when_the_glb_was_last_written() -> None:
    glb = make_model("bear") / "model.glb"
    make_model("owl", minutes=None)
    os.utime(glb, (START.timestamp(), START.timestamp()))
    first = {model.name: model.built for model in lib.list_3d_models().models}
    rebuilt = START + timedelta(minutes=5)
    os.utime(glb, (rebuilt.timestamp(), rebuilt.timestamp()))

    assert first == {"bear": START, "owl": None}
    assert lib.list_3d_models().models[0].built == rebuilt


def test_a_run_whose_process_is_gone_lists_as_crashed_and_is_left_as_it_is() -> None:
    crashed = make_model("bear", status="running", pid=GONE_PID)
    make_model("fox", status="running", pid=os.getpid())
    before = (crashed / "model.json").read_bytes()

    statuses = {model.name: model.status for model in lib.list_3d_models().models}

    assert statuses == {"bear": "crashed", "fox": "running"}
    assert (crashed / "model.json").read_bytes() == before


def test_a_broken_record_is_named_in_unreadable_and_the_rest_still_list() -> None:
    make_model("bear")
    broken = make_model("broken")
    (broken / "model.json").write_text("{", encoding="utf-8")
    alien = make_model("alien")
    (alien / "model.json").write_text('{"tool": "another-tool"}', encoding="utf-8")

    listing = lib.list_3d_models()

    assert [model.name for model in listing.models] == ["bear"]
    assert len(listing.unreadable) == 2
    for message, target in zip(listing.unreadable, [alien, broken], strict=True):
        assert str((target / "model.json").resolve()) in message
        assert "Fix or remove it." in message


def test_viewing_a_model_makes_it_the_one_viewed_last() -> None:
    make_model("bear")
    make_model("fox", minutes=30)

    summary = lib.view_3d_model("bear")
    after_bear = lib.list_3d_models()
    lib.view_3d_model("fox")

    assert summary == after_bear.models[1]
    assert after_bear.last_viewed == "bear"
    assert lib.list_3d_models().last_viewed == "fox"


def test_viewing_models_at_once_never_fails() -> None:
    make_model("bear")
    make_model("fox", minutes=30)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda index: lib.view_3d_model(("bear", "fox")[index % 2]), range(200)))

    assert lib.list_3d_models().last_viewed in ("bear", "fox")
    assert [path.name for path in Path(".modeling-3d").iterdir() if path.suffix == ".tmp"] == []


def test_viewing_records_the_model_in_the_directory_it_names(working_directory: Path) -> None:
    make_model("bear", root=Path("models"))

    lib.view_3d_model("bear", Path("models"))

    assert lib.list_3d_models(Path("models")).last_viewed == "bear"
    assert lib.list_3d_models().last_viewed is None
    assert (working_directory / "models" / ".state.json").is_file()


@pytest.mark.parametrize("name", ["fox", "Bear", "../bear", "notes"])
def test_viewing_a_model_that_does_not_exist_names_the_ones_that_do(working_directory: Path, name: str) -> None:
    make_model("bear")
    (working_directory / ".modeling-3d" / "notes").mkdir()

    with pytest.raises(Modeling3dError) as failure:
        lib.view_3d_model(name)

    assert f"There is no model named {name!r}" in str(failure.value)
    assert "The models there: bear." in str(failure.value)
    assert not (working_directory / ".modeling-3d" / ".state.json").exists()


def test_a_removed_model_or_an_unreadable_state_reads_as_nothing_viewed(working_directory: Path) -> None:
    bear = make_model("bear")
    make_model("fox")
    state = working_directory / ".modeling-3d" / ".state.json"

    lib.view_3d_model("bear")
    shutil.rmtree(bear)
    removed = lib.list_3d_models().last_viewed
    state.write_text("not json", encoding="utf-8")
    unreadable = lib.list_3d_models().last_viewed
    lib.view_3d_model("fox")

    assert (removed, unreadable) == (None, None)
    assert lib.list_3d_models().last_viewed == "fox"


def test_the_cli_prints_the_listing_and_the_summary_as_json_and_fails_on_an_unknown_model() -> None:
    make_model("bear")

    viewed = runner.invoke(app, ["view-3d-model", "--name", "bear"])
    listed = runner.invoke(app, ["list-3d-models"])
    unknown = runner.invoke(app, ["view-3d-model", "--name", "fox"])

    assert viewed.exit_code == listed.exit_code == 0, viewed.output + listed.output
    listing = ModelListing.model_validate_json(listed.stdout)
    assert listing.last_viewed == "bear"
    assert ModelSummary.model_validate_json(viewed.stdout) == listing.models[0]
    assert unknown.exit_code == 1
    assert isinstance(unknown.exception, Modeling3dError)
    assert "There is no model named 'fox'" in str(unknown.exception)
