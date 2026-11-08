"""Lists, views, renames, and deletes models whose model.json is written directly, so no agent is needed."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil
import stat

from fakes import run_record
import pytest
from typer.testing import CliRunner

from modeling_3d import lib
from modeling_3d.capabilities.create_3d_model.record import load_record, write_record
from modeling_3d.cli import app
from modeling_3d.schemas import (
    AgentProvider,
    ModelCheck,
    Modeling3dError,
    ModelListing,
    ModelRecord,
    ModelRunStatus,
    ModelSummary,
)

START = datetime(2026, 10, 17, 10, tzinfo=UTC)
# Above Linux's highest pid and never handed out on Windows, so no process has it.
GONE_PID = 2**22 + 7

runner = CliRunner()
pytestmark = pytest.mark.usefixtures("working_directory")


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
            run_record(
                id=f"run-{name}",
                prompt=f"A {name}",
                session_id=f"session-{name}",
                status=status,
                pid=pid,
                started=started,
                last_event=started + timedelta(minutes=1),
            )
        )
        (target / "model.py").write_text("# the model", encoding="utf-8")
        (target / "model.glb").write_bytes(b"glTF")
    write_record(target, ModelRecord(id=f"id-{name}", name=name, created=START - timedelta(days=1), runs=runs))
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
    record = load_record(bear)
    session = record.runs[0].model_copy(update={"agent_provider": agent_provider, "session_id": "0199f1c2-thread"})
    unstarted = session.model_copy(update={"id": "run-unstarted", "session_id": None, "status": "failed"})
    record.runs = [session, unstarted]
    write_record(bear, record)
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
    before = (crashed / "runs.json").read_bytes()

    statuses = {model.name: model.status for model in lib.list_3d_models().models}

    assert statuses == {"bear": "crashed", "fox": "running"}
    assert (crashed / "runs.json").read_bytes() == before


def test_a_model_cloned_without_its_runs_lists_as_never_run() -> None:
    (make_model("bear") / "runs.json").unlink()

    [summary] = lib.list_3d_models().models

    assert (summary.status, summary.last_run, summary.updated) == (None, None, START - timedelta(days=1))


def test_a_broken_record_is_named_in_unreadable_and_the_rest_still_list() -> None:
    make_model("bear")
    broken = make_model("broken")
    (broken / "model.json").write_text("{", encoding="utf-8")
    alien = make_model("alien")
    (alien / "model.json").write_text('{"tool": "another-tool"}', encoding="utf-8")
    runless = make_model("runless")
    (runless / "runs.json").write_text('{"runs": [{}]}', encoding="utf-8")

    listing = lib.list_3d_models()

    assert [model.name for model in listing.models] == ["bear"]
    assert len(listing.unreadable) == 3
    for message, path in zip(
        listing.unreadable, [alien / "model.json", broken / "model.json", runless / "runs.json"], strict=True
    ):
        assert str(path.resolve()) in message
        assert "Fix" in message


def test_viewing_a_model_makes_it_the_one_viewed_last_in_its_directory(working_directory: Path) -> None:
    make_model("bear")
    make_model("fox", minutes=30)
    make_model("owl", root=Path("models"))

    summary = lib.view_3d_model("bear")
    after_bear = lib.list_3d_models()
    lib.view_3d_model("fox")
    lib.view_3d_model("owl", Path("models"))

    assert summary == after_bear.models[1]
    assert after_bear.last_viewed == "bear"
    assert lib.list_3d_models().last_viewed == "fox"
    assert lib.list_3d_models(Path("models")).last_viewed == "owl"
    assert (working_directory / "models" / ".state.json").is_file()


def test_viewing_models_at_once_never_fails() -> None:
    make_model("bear")
    make_model("fox", minutes=30)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda index: lib.view_3d_model(("bear", "fox")[index % 2]), range(200)))

    assert lib.list_3d_models().last_viewed in ("bear", "fox")
    assert [path.name for path in Path(".modeling-3d").iterdir() if path.suffix == ".tmp"] == []


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


def report_of(target: Path) -> ModelCheck:
    """A check of the model, kept in its checks/ as `check_3d_model` keeps one."""
    report = ModelCheck(
        name=target.name,
        directory=target,
        checked=START,
        glb_sha256="0" * 64,
        max_triangles=None,
        max_draw_calls=None,
        screen_size=None,
        dimensions=(1.0, 1.0, 1.0),
        bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        triangles=12,
        mesh_objects=1,
        materials=0,
        checks=[],
    )
    (target / "checks").mkdir()
    (target / "checks" / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def opt_in(root: Path) -> Path:
    """The models directory's .gitignore, opting in bear's sources, and those of models only named alike."""
    ignores = root / ".gitignore"
    ignores.write_text("/*\n!/bear/\n!/bear/notes.md\n!/bearish/\n!/fox/\n", encoding="utf-8")
    return ignores


def test_renaming_a_model_moves_it_with_what_names_it_and_leaves_its_history(working_directory: Path) -> None:
    root = working_directory / ".modeling-3d"
    bear = make_model("bear").resolve()
    report = report_of(bear)
    (bear / "runs" / "run-bear").mkdir(parents=True)
    events = bear / "runs" / "run-bear" / "events.jsonl"
    events.write_text(f"Working in {bear}\n", encoding="utf-8")
    make_model("fox", minutes=30)
    ignores = opt_in(root)
    lib.view_3d_model("bear")
    history = events.read_bytes()

    summary = lib.rename_3d_model("bear", "grizzly")

    grizzly = root / "grizzly"
    listing = lib.list_3d_models()
    assert not bear.exists()
    assert (summary.name, summary.id, summary.directory) == ("grizzly", "id-bear", grizzly)
    assert summary == listing.models[1]
    assert listing.last_viewed == "grizzly"
    record = load_record(grizzly)
    assert record.name == "grizzly"
    assert [run.directory for run in record.runs] == [bear]
    assert ModelCheck.model_validate_json((grizzly / "checks" / "report.json").read_text(encoding="utf-8")) == (
        report.model_copy(update={"name": "grizzly", "directory": grizzly})
    )
    assert ignores.read_text(encoding="utf-8") == "/*\n!/grizzly/\n!/grizzly/notes.md\n!/bearish/\n!/fox/\n"
    assert (grizzly / "runs" / "run-bear" / "events.jsonl").read_bytes() == history
    assert (grizzly / "model.py").read_text(encoding="utf-8") == "# the model"


@pytest.mark.parametrize(
    ("new_name", "reason", "named"),
    [
        ("../wolf", "invalid-name", "cannot name a model"),
        (".hidden", "invalid-name", "cannot name a model"),
        ("Fox", "name-in-use", "is already another model"),
        ("NOTES", "name-in-use", "is already something that is not a model"),
    ],
)
def test_a_name_the_tool_would_not_give_or_one_held_ignoring_case_is_refused_with_nothing_changed(
    working_directory: Path, new_name: str, reason: str, named: str
) -> None:
    root = working_directory / ".modeling-3d"
    make_model("bear")
    make_model("fox")
    (root / "notes").mkdir()
    before = sorted(path.name for path in root.iterdir())

    with pytest.raises(Modeling3dError) as failure:
        lib.rename_3d_model("bear", new_name)

    assert failure.value.reason == reason
    assert named in str(failure.value)
    assert sorted(path.name for path in root.iterdir()) == before
    assert load_record(root / "bear").name == "bear"


def test_a_rename_of_only_the_case_renames_it_and_one_to_the_same_name_changes_nothing(working_directory: Path) -> None:
    root = working_directory / ".modeling-3d"
    make_model("bear")

    same = lib.rename_3d_model("bear", "bear")
    cased = lib.rename_3d_model("bear", "Bear")

    assert same.name == "bear"
    assert [path.name for path in root.iterdir()] == ["Bear"]
    assert (cased.name, load_record(root / "Bear").name) == ("Bear", "Bear")


def test_deleting_a_model_removes_all_of_it_with_what_names_it_and_leaves_the_rest(working_directory: Path) -> None:
    root = working_directory / ".modeling-3d"
    bear = make_model("bear")
    (bear / "references").mkdir()
    locked = bear / "references" / "locked.png"
    locked.write_bytes(b"png")
    locked.chmod(stat.S_IREAD)
    fox = make_model("fox", minutes=30)
    ignores = opt_in(root)
    lib.view_3d_model("bear")

    lib.delete_3d_model("bear")

    listing = lib.list_3d_models()
    assert not bear.exists()
    assert sorted(path.name for path in root.iterdir()) == [".gitignore", ".state.json", "fox"]
    assert ([model.name for model in listing.models], listing.last_viewed) == (["fox"], None)
    assert ignores.read_text(encoding="utf-8") == "/*\n!/bearish/\n!/fox/\n"
    assert (fox / "model.py").is_file()


@pytest.mark.parametrize("name", ["fox", "Bear", "../bear", "notes", ".deleting-bear-0a1b2c"])
def test_renaming_or_deleting_anything_but_a_model_by_its_exact_name_names_the_models_there(
    working_directory: Path, name: str
) -> None:
    root = working_directory / ".modeling-3d"
    make_model("bear")
    make_model(".deleting-bear-0a1b2c")
    (root / "notes").mkdir()

    for act in (lambda: lib.rename_3d_model(name, "wolf"), lambda: lib.delete_3d_model(name)):
        with pytest.raises(Modeling3dError) as failure:
            act()
        assert failure.value.reason == "no-such-model"
        assert "The models there: bear." in str(failure.value)
    assert sorted(path.name for path in root.iterdir()) == [".deleting-bear-0a1b2c", "bear", "notes"]


def test_a_folder_a_delete_left_never_lists_and_one_named_by_hand_still_does() -> None:
    make_model(".deleting-bear-0a1b2c")
    make_model("My Bear")

    listed = [model.name for model in lib.list_3d_models().models]
    renamed = lib.rename_3d_model("My Bear", "my-bear").name
    lib.delete_3d_model("my-bear")

    assert (listed, renamed) == (["My Bear"], "my-bear")
    assert lib.list_3d_models().models == []


def test_a_run_working_on_a_model_refuses_a_rename_and_in_this_process_a_delete_and_a_crashed_one_neither() -> None:
    make_model("bear", status="running", pid=os.getpid())
    make_model("fox", status="running", pid=GONE_PID)

    with pytest.raises(Modeling3dError) as renaming:
        lib.rename_3d_model("bear", "grizzly")
    with pytest.raises(Modeling3dError) as deleting:
        lib.delete_3d_model("bear")
    lib.rename_3d_model("fox", "wolf")
    lib.delete_3d_model("wolf")

    assert (renaming.value.reason, renaming.value.model) == ("model-busy", "bear")
    assert "`modeling-3d cancel-3d-model --name bear`" in str(renaming.value)
    assert (deleting.value.reason, deleting.value.model) == ("model-busy", "bear")
    assert "`await run.cancel()`" in str(deleting.value)
    assert [model.name for model in lib.list_3d_models().models] == ["bear"]


def test_the_cli_renames_printing_the_summary_and_deletes_printing_nothing_and_each_fails_naming_the_fix() -> None:
    make_model("bear")

    renamed = runner.invoke(app, ["rename-3d-model", "--name", "bear", "--new-name", "grizzly"])
    invalid = runner.invoke(app, ["rename-3d-model", "--name", "grizzly", "--new-name", "a bear"])
    deleted = runner.invoke(app, ["delete-3d-model", "--name", "grizzly"])
    again = runner.invoke(app, ["delete-3d-model", "--name", "grizzly"])

    assert renamed.exit_code == deleted.exit_code == 0, renamed.output + deleted.output
    assert ModelSummary.model_validate_json(renamed.stdout).name == "grizzly"
    assert deleted.stdout == ""
    assert invalid.exit_code == again.exit_code == 1
    assert isinstance(invalid.exception, Modeling3dError)
    assert "cannot name a model" in str(invalid.exception)
    assert "There is no model named 'grizzly'" in str(again.exception)
