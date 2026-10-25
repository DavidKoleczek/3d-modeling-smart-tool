"""What a model's agent is sent: the templates in prompts/, filled with the text in constants.py."""

from pathlib import Path

from modeling_3d.capabilities.create_3d_model.budgets import resolved
from modeling_3d.capabilities.create_3d_model.constants import (
    ADDED_REFERENCES,
    AT_MOST,
    ATTACHED,
    CHANGED_MODE,
    COLOR_DRAW_CALL_ADVICE,
    COLOR_SCREEN_ADVICE,
    DETAIL_DRAW_CALL_ADVICE,
    DETAIL_SCREEN_ADVICE,
    DRAW_CALL,
    EXISTING,
    FOLDER,
    KEEP,
    KEPT,
    MODE_CAPABILITIES,
    MODE_PROMPTS,
    NO_BUDGET,
    ON_SCREEN,
    READ_GUIDANCE,
    REFERENCES,
    RIG_DRAW_CALL_ADVICE,
    SCREEN_SIZE,
    SHAPE_SCREEN_ADVICE,
    TRIANGLE,
    UNASKED,
)
from modeling_3d.capabilities.create_3d_model.record import GUIDANCE
from modeling_3d.capabilities.create_3d_model.references import attached
from modeling_3d.schemas import BPY_REQUIREMENT, ModelMode, ModelRunRecord, NotGiven

PROMPTS = Path(__file__).parent / "prompts"


def template(name: str) -> str:
    """The template in prompts/ by that name."""
    return (PROMPTS / name).read_text(encoding="utf-8")


def prompt(
    run: ModelRunRecord,
    target: Path,
    root: Path,
    budgets: str,
    resumed: ModelRunRecord | None,
    created: bool,
    kept: list[ModelMode],
) -> str:
    """The run's prompt: its request and all the agent needs for it, or for a session going on, what is new to it.

    `kept` are the modes whose work, from earlier requests, a fresh session on the model is told to keep working.
    """
    request = run.prompt or UNASKED.get(run.mode, "")
    instructions = template(MODE_PROMPTS[run.mode]).strip()
    if resumed is not None:
        mode = "" if resumed.mode == run.mode else f"\n{CHANGED_MODE}\n\n{instructions}\n"
        return template("resume.md").format(
            request=request, mode=mode, budgets=budgets, references=listed(run.references, ADDED_REFERENCES)
        )
    existing = ""
    if not created:
        existing = f"\n{EXISTING}"
        existing += f" {KEEP.format(kept=_joined([KEPT[mode] for mode in kept]))}\n" if kept else "\n"
    return template("fresh_session.md").format(
        capability=MODE_CAPABILITIES[run.mode],
        request=request,
        mode=instructions,
        budgets=budgets,
        directory=target,
        name=target.name,
        models=root,
        guidance=_guidance(root),
        bpy=BPY_REQUIREMENT,
        references=listed(run.references, REFERENCES),
        existing=existing,
    )


def _joined(items: list[str]) -> str:
    """The items as a sentence lists them."""
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def budgets_block(
    mode: ModelMode,
    triangles: int | None,
    draw_calls: int | None,
    on_screen: tuple[int, int] | None,
    removed: list[str] | None = None,
) -> str:
    """The budgets, how the mode keeps to each, and any a session going on no longer has; nothing without any."""
    lines: list[str] = []
    advice: list[str] = []
    if triangles is not None:
        lines.append(_at_most(triangles, TRIANGLE))
    if draw_calls is not None:
        lines.append(_at_most(draw_calls, DRAW_CALL))
    if draw_calls is not None:
        advice += {
            "rig": RIG_DRAW_CALL_ADVICE,
            "color": COLOR_DRAW_CALL_ADVICE,
            "detail": DETAIL_DRAW_CALL_ADVICE,
        }.get(mode, ())
    if on_screen is not None:
        smallest, largest = on_screen
        lines.append(ON_SCREEN.format(smallest=smallest, largest=largest))
        advice += {
            "shape": SHAPE_SCREEN_ADVICE,
            "color": COLOR_SCREEN_ADVICE,
            "detail": DETAIL_SCREEN_ADVICE,
        }.get(mode, ())
    lines += [NO_BUDGET.format(name=name) for name in removed or []]
    if not lines:
        return ""
    block = template("budgets.md").format(budgets="\n".join(lines), advice="\n".join(advice))
    return "\n" + block.rstrip("\n") + "\n"


def changed_budgets_block(
    mode: ModelMode,
    max_triangles: int | NotGiven | None,
    max_draw_calls: int | NotGiven | None,
    screen_size: tuple[int, int] | NotGiven | None,
) -> str:
    """The budgets a request sets and removes, for a session that has the model's own already."""
    given = ((TRIANGLE[0], max_triangles), (DRAW_CALL[0], max_draw_calls), (SCREEN_SIZE, screen_size))
    removed = [name for name, budget in given if budget is None]
    return budgets_block(
        mode, resolved(max_triangles, None), resolved(max_draw_calls, None), resolved(screen_size, None), removed
    )


def steering(message: str, references: list[str]) -> str:
    """A steering message as the agent gets it, with the references sent with it."""
    return message + listed(references, ADDED_REFERENCES)


def listed(references: list[str], heading: str) -> str:
    """The references, for the agent to find, after the request or message they came with."""
    if not references:
        return ""
    lines = [f"- {path}{_noted(path)}" for path in references]
    return f"\n{heading}\n" + "\n".join(lines) + "\n"


def _at_most(count: int, noun: tuple[str, str]) -> str:
    singular, plural = noun
    return AT_MOST.format(count=count, noun=singular if count == 1 else plural)


def _guidance(root: Path) -> str:
    """Where the project's guidance for the models in `root` is, for the agent to read; nothing without one."""
    path = root / GUIDANCE
    return READ_GUIDANCE.format(path=path) if path.is_file() else ""


def _noted(reference: str) -> str:
    if reference.endswith("/"):
        return FOLDER
    return ATTACHED if attached(reference) else ""
