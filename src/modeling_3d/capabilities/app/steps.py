"""Which groups of steps the person opened or closed in each model's activity, kept for its models directory."""

from pathlib import Path

from modeling_3d.capabilities.app.settings import write_atomically
from modeling_3d.schemas import APP_STATE_FOLDER, AppSteps, Modeling3dError

STEPS = "steps.json"


def steps_path(directory: Path) -> Path:
    """Where the steps opened or closed in the models `directory` are kept."""
    return directory / APP_STATE_FOLDER / STEPS


def read_activity_steps(directory: Path) -> AppSteps:
    """The steps opened or closed in the models `directory`; none when there are none yet, or they cannot be read."""
    try:
        return AppSteps.model_validate_json(steps_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSteps()


def save_activity_step(directory: Path, model_id: str, group: str, opened: bool, models: set[str]) -> AppSteps:
    """Keep the `group` of steps in the activity of the model `model_id` as `opened` or closed, forgetting those of
    models no longer among `models`, and return what is kept."""
    before = read_activity_steps(directory)
    # A model deleted takes its id with it, so what was kept for it is dropped here rather than kept for good.
    steps = {kept: groups for kept, groups in before.steps.items() if kept in models}
    steps[model_id] = {**steps.get(model_id, {}), group: opened}
    after = AppSteps(steps=steps)
    path = steps_path(directory)
    try:
        write_atomically(path, after.model_dump_json(indent=2))
    except OSError as error:
        raise Modeling3dError(
            f"Could not save the steps opened in {model_id}'s activity to {path}: {error}. Check that the folder can "
            "be written."
        ) from None
    return after
