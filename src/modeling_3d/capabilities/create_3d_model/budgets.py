"""A model's budgets as a request gives them: a number, None for no budget, or left out for the one kept."""

from modeling_3d.schemas import Modeling3dError, NotGiven


def require_budgets(
    max_triangles: int | NotGiven | None,
    max_draw_calls: int | NotGiven | None,
    screen_size: tuple[int, int] | NotGiven | None,
) -> None:
    for name, budget in (("max_triangles", max_triangles), ("max_draw_calls", max_draw_calls)):
        if isinstance(budget, int) and budget < 1:
            raise Modeling3dError(
                f"{name} is {budget}, and a budget is 1 or more. Pass None (--{name.replace('_', '-')} none) for no "
                "budget.",
                "bad-budget",
            )
    if isinstance(screen_size, tuple) and (
        len(screen_size) != 2 or min(screen_size) < 1 or screen_size[0] > screen_size[1]
    ):
        raise Modeling3dError(
            f"screen_size is {screen_size}. Give the smallest and then the largest the model is on screen, in pixels "
            "along its longest side at 1080p, each 1 or more, such as --screen-size 40-240 (screen_size=(40, 240)).",
            "bad-budget",
        )


def resolved[Budget](given: Budget | NotGiven | None, kept: Budget | None) -> Budget | None:
    """The budget given, or `kept` when it was left out."""
    return kept if isinstance(given, NotGiven) else given
