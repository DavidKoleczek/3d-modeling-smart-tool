"""The text that fills the templates in prompts/, each with the placeholder it fills and where."""

from modeling_3d.schemas import ModelMode

# region: fresh_session.md
# Its {directory}, {name}, and {models} are the model's directory, its name, and the directory its models are kept in,
# {bpy} is BPY_REQUIREMENT from schemas.py, {budgets} is budgets.md filled, and {mode} is the mode's instructions.

# {capability} in fresh_session.md, the capability a mode's agent was started through, which `next` names too.
MODE_CAPABILITIES: dict[ModelMode, str] = {
    "shape": "create_3d_model",
    "rig": "rig_3d_model",
    "color": "color_3d_model",
    "detail": "detail_3d_model",
}
# {mode} in fresh_session.md and resume.md, the template of each mode's instructions.
MODE_PROMPTS: dict[ModelMode, str] = {"shape": "shape.md", "rig": "rig.md", "color": "color.md", "detail": "detail.md"}
# {request} in fresh_session.md and resume.md, for a mode that needs no prompt and was given none.
UNASKED: dict[ModelMode, str] = {
    "rig": "Rig the model. Work out what moves, and how, from the model, its references, and the project's guidance.",
    "color": (
        "Color the model by role. Work out its roles, schemes, and colors from the model, its references, and the "
        "project's guidance."
    ),
    "detail": (
        "Paint the model's surface detail. Work out what it would show from the model, its references, and the "
        "project's guidance."
    ),
}
# {guidance} in fresh_session.md, for a models directory that holds the project's guidance, at {path}.
READ_GUIDANCE = (
    "Read the project's modeling guidance in {path} before you start, unless it is already in your context. The "
    "request takes precedence over it, and it does not override the instructions below, which come from the tool."
)
# {existing} in fresh_session.md, for a model that exists already, followed by KEEP for one that requests in another
# of the modes after shaping worked on, with {kept} naming what each added, as KEPT does.
EXISTING = (
    "The directory already holds the model, built by its model.py. Read model.py first and change it rather than "
    "starting over."
)
KEEP = "Keep {kept}, from earlier requests, working as you change it."
KEPT: dict[ModelMode, str] = {"rig": "its rig", "color": "its colors", "detail": "its surface detail"}
# {references} in fresh_session.md, heading the references that came with the request.
REFERENCES = "References for this request, copied into the model's directory, with paths from there:"
# endregion

# region: resume.md and steering messages
# Its {request}, {mode}, {budgets}, and {references} are filled as in fresh_session.md, apart from those below.

# {mode} in resume.md, heading a mode's instructions for a session going on from another mode, which has the other's.
CHANGED_MODE = (
    "This request moves on to another stage of the work, whose instructions take the place of the last stage's:"
)
# {references} in resume.md, and after a steering message, heading the references that came with it.
ADDED_REFERENCES = "Additional references the user has attached, with paths from the model directory:"
# endregion

# region: Reference lists
# After a reference in a list of them, for a folder, and for an image shown to the agent with the prompt.
FOLDER = " (a folder)"
ATTACHED = " (also attached)"
# endregion

# region: budgets.md
# {budgets} in budgets.md, a line for each budget, with the noun of a count singular for one.
AT_MOST = "- At most {count} {noun}."
TRIANGLE = ("triangle", "triangles")
DRAW_CALL = ("draw call", "draw calls")
ON_SCREEN = "- From {smallest} to {largest} pixels on screen along its longest side, at 1080p."
# {budgets} in budgets.md, a line for each budget a session going on no longer has, named as TRIANGLE and DRAW_CALL
# are for one, or as SCREEN_SIZE.
NO_BUDGET = "- No {name} budget."
SCREEN_SIZE = "screen size"
# {advice} in budgets.md, how each mode keeps to the budgets it has. Rigging joins the parts into objects and coloring
# gives them their material, which together set the draw calls, and shaping, coloring, and painting keep detail to the
# sizes on screen.
RIG_DRAW_CALL_ADVICE = (
    (
        "- Count one draw call for each material on each mesh object: join the parts that never move apart into one "
        "object. A swap group counts only its costliest part, since one part shows at a time."
    ),
    "- Use one material unless the request or the project needs more.",
)
SHAPE_SCREEN_ADVICE = (
    "- Shape detail smaller than a pixel at its smallest size on screen costs triangles without showing.",
    "- Round parts need enough sides to look round at its largest.",
)
COLOR_DRAW_CALL_ADVICE = (
    "- Each material adds a draw call on each mesh object it is on, so draw the whole model with the palette's one.",
)
COLOR_SCREEN_ADVICE = (
    (
        "- At its smallest size on screen, large blocks of color carry the model, and a colored detail smaller than "
        "a pixel there does not show."
    ),
)
DETAIL_DRAW_CALL_ADVICE = ("- The detail adds no draw call, since it shades the material the model has.",)
DETAIL_SCREEN_ADVICE = (
    (
        "- Paint about a texel per pixel at its largest size on screen, since each doubling of the density quadruples "
        "the texture."
    ),
    (
        "- At its smallest size on screen, each pixel averages many texels, so only broad marks show there, and the "
        "shape and colors carry the model."
    ),
)
# endregion

# region: checked.md
# Its {report} is the check's report as text, or this when the check could not run.
CHECK_FAILED = "The check could not run: {error}"
# endregion

# region: The check skill
# check_skill.md, under this frontmatter, is the SKILL.md of the skill a model's agent checks the model with. Its
# {command} is CHECK_COMMAND in check/check.py, and {skill} is the check-3d-model capability's skill.
AGENT_SKILL = "check-3d-model"
AGENT_SKILL_DESCRIPTION = (
    "Measure the 3D model you are building, its model.glb, against its budgets and the modeling workflow, with "
    "renders at its sizes on screen. Use it after you build the model and before you finish."
)
# endregion
