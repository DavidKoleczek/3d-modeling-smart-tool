"""What the app's MCP server offers: the tool that opens the app, the tools its view calls, and its resources."""

from typing import Any

from mcp.server.apps import APP_MIME_TYPE
from mcp.types import Resource, ResourceTemplate, Tool

from modeling_3d.schemas import AGENT_PROVIDERS, REASONING_EFFORTS

VIEW_URI = "ui://modeling-3d/app"
MODEL_FILE_PREFIX = "modeling-3d://models/"
APP_ONLY = {"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}}
# Copy buttons in the view write to the clipboard, which a sandboxed frame may only do when its host allows it.
VIEW_META = {"ui": {"permissions": {"clipboardWrite": {}}}}
OPEN_APP = Tool(
    name="open_app",
    description="Show the 3D Modeling app, where the user watches the models in a directory being made, and creates, "
    "changes, and steers them, and return its browser URL. Hosts that render MCP Apps show it inline. Opening it "
    "again returns the same URL.",
    input_schema={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Where the models to show are kept, absolute or relative to where this server started. "
                "Omit it to keep the current one, .modeling-3d in the working directory at first.",
            }
        },
    },
    _meta={"ui": {"resourceUri": VIEW_URI}},
)
LIST_MODELS = Tool(
    name="list_3d_models",
    description="The models in the app's directory, newest first, with their state, and the one viewed last. Called "
    "by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
VIEW_MODEL = Tool(
    name="view_3d_model",
    description="Record a model in the app's directory as the one viewed last, and return its summary. Called by the "
    "view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta=APP_ONLY,
)
# What every request that starts a run on a model takes, whatever its mode.
RUN_PROPERTIES: dict[str, Any] = {
    "name": {"type": "string"},
    "resume_session": {"type": ["boolean", "string"]},
    "agent_provider": {"type": "string", "enum": list(AGENT_PROVIDERS)},
    "model": {"type": "string"},
    "reasoning_effort": {"type": "string", "enum": list(REASONING_EFFORTS)},
    "reference_models": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Models in the app's directory, whose script, GLB, and first render are references",
    },
    "uploads": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Uploads from `upload_reference`, each a file or a folder to work from",
    },
}
CREATE_MODEL = Tool(
    name="create_3d_model",
    description="Create a model in the app's directory, or change the shape of the one by that name, in a run of its "
    "own that outlives this server; return the model's summary once its agent runs, and record it as viewed last. "
    "Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            **RUN_PROPERTIES,
            "max_triangles": {"type": ["integer", "null"], "description": "Null for no budget; left out, the default"},
            "max_draw_calls": {"type": ["integer", "null"], "description": "As for max_triangles"},
            "screen_size": {
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "The smallest and largest it is on screen, in pixels along its longest side at 1080p; "
                "as for max_triangles",
            },
        },
        "required": ["prompt", "name"],
    },
    _meta=APP_ONLY,
)
RIG_MODEL = Tool(
    name="rig_3d_model",
    description="Rig a built model in the app's directory, to its own budgets, in a run of its own that outlives this "
    "server; return the model's summary once its agent runs, and record it as viewed last. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Left out, the agent works out what moves"},
            **RUN_PROPERTIES,
        },
        "required": ["name"],
    },
    _meta=APP_ONLY,
)
COLOR_MODEL = Tool(
    name="color_3d_model",
    description="Color a built model in the app's directory by role, to its own budgets, in a run of its own that "
    "outlives this server; return the model's summary once its agent runs, and record it as viewed last. Called by the "
    "view.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Left out, the agent works out the roles and colors"},
            **RUN_PROPERTIES,
        },
        "required": ["name"],
    },
    _meta=APP_ONLY,
)
DETAIL_MODEL = Tool(
    name="detail_3d_model",
    description="Paint the surface detail of a built model in the app's directory, to its own budgets, in a run of its "
    "own that outlives this server; return the model's summary once its agent runs, and record it as viewed last. "
    "Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Left out, the agent works out what to paint"},
            **RUN_PROPERTIES,
        },
        "required": ["name"],
    },
    _meta=APP_ONLY,
)
CHECK_MODEL = Tool(
    name="check_3d_model",
    description="Check a model in the app's directory against its own budgets, and return the report, which is also "
    'kept in its checks/report.json. A check that takes a while returns {"checking": true} first; calling again '
    "waits on the same check. Called by the view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta=APP_ONLY,
)
UPLOAD_REFERENCE = Tool(
    name="upload_reference",
    description="Receive a piece of a file the person added to work from, written at `offset` into the upload named "
    "`upload`, and return how much of the file has arrived. `create_3d_model` takes the upload once every piece has. "
    "Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "upload": {"type": "string", "description": "An id of the view's own, in hex, one per file or folder"},
            "path": {"type": "string", "description": "The file's name, or its path in the folder added"},
            "offset": {"type": "integer", "minimum": 0},
            "data": {"type": "string", "description": "Base64"},
        },
        "required": ["upload", "path", "offset", "data"],
    },
    _meta=APP_ONLY,
)
STEER_MODEL = Tool(
    name="steer_3d_model",
    description="Send a message to the agent working on a model in the app's directory. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "message": {"type": "string"},
            "uploads": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Uploads from `upload_reference`, each a file or a folder to send with the message",
            },
        },
        "required": ["name", "message"],
    },
    _meta=APP_ONLY,
)
CANCEL_MODEL = Tool(
    name="cancel_3d_model",
    description="Stop the run working on a model in the app's directory. Called by the view.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _meta=APP_ONLY,
)
READ_ACTIVITY = Tool(
    name="read_3d_model_activity",
    description="A model's summary and its activity, or only what came after the cursor `after`. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}, "after": {"type": "string"}},
        "required": ["name"],
    },
    _meta=APP_ONLY,
)
READ_TOOL_CALL = Tool(
    name="read_3d_model_tool_call",
    description="One tool call of a model's agent in full, by the `run_id` and `call_id` of its entry in the model's "
    "activity. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}, "run_id": {"type": "string"}, "call_id": {"type": "string"}},
        "required": ["name", "run_id", "call_id"],
    },
    _meta=APP_ONLY,
)
LIST_INTELLIGENCE = Tool(
    name="list_intelligence_models",
    description="The AI models and reasoning efforts to pick from, and the ones the person picked last in the app's "
    "directory. Called by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
CHOOSE_INTELLIGENCE = Tool(
    name="choose_intelligence_model",
    description="Remember an AI model and reasoning effort as the ones the person picked last in the app's "
    "directory, and return what can be picked. Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "reasoning_effort": {"type": "string", "enum": list(REASONING_EFFORTS)},
        },
        "required": ["model", "reasoning_effort"],
    },
    _meta=APP_ONLY,
)
READ_SETTINGS = Tool(
    name="read_app_settings",
    description="How the person set up the app: theme, viewport tools, pane sizes, and the steps they opened in each "
    "model's activity, the same in every directory. Called by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
SAVE_SETTINGS = Tool(
    name="save_app_settings",
    description="Keep the app's settings for the person, replacing the ones kept before, and return them. Called by "
    "the view.",
    input_schema={
        "type": "object",
        "properties": {"settings": {"type": "object", "description": "As `read_app_settings` returns them"}},
        "required": ["settings"],
    },
    _meta=APP_ONLY,
)
READ_FOLDERS = Tool(
    name="read_app_folders",
    description="Where the app keeps the person's settings, and the models it shows. Called by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
OPEN_FOLDER = Tool(
    name="open_app_folder",
    description="Open the folder of the person's settings, of the app's models, or of one model in their file manager. "
    "Called by the view.",
    input_schema={
        "type": "object",
        "properties": {
            "folder": {"type": "string", "enum": ["settings", "models", "model"]},
            "name": {"type": "string", "description": "The model, for `model`"},
        },
        "required": ["folder"],
    },
    _meta=APP_ONLY,
)
VIEW_TOOLS = [
    LIST_MODELS,
    VIEW_MODEL,
    CREATE_MODEL,
    RIG_MODEL,
    COLOR_MODEL,
    DETAIL_MODEL,
    CHECK_MODEL,
    UPLOAD_REFERENCE,
    STEER_MODEL,
    CANCEL_MODEL,
    READ_ACTIVITY,
    READ_TOOL_CALL,
    LIST_INTELLIGENCE,
    CHOOSE_INTELLIGENCE,
    READ_SETTINGS,
    SAVE_SETTINGS,
    READ_FOLDERS,
    OPEN_FOLDER,
]
VIEW = Resource(uri=VIEW_URI, name="3D Modeling app", mime_type=APP_MIME_TYPE)
MODEL_FILE = ResourceTemplate(
    name="Model file",
    uri_template=f"{MODEL_FILE_PREFIX}{{name}}/{{+path}}",
    description="A model's GLB, one of its renders, a reference image it was given, or its latest check's report or "
    "renders, as base64, for the app's view.",
)
