"""OpenAI-style tool schemas for the agent loop.

submit_blueprint / str_replace / edit_region / inspect / finish.
"""

# Hard cap on renderings per build: each view is a full rasterization and the sheet is
# resent to the model every iteration, so an uncapped list is unbounded render/token cost.
# The agent loop re-validates against this at runtime (LLMs don't reliably honor schemas).
MAX_VIEWS = 8

# Shared by submit_blueprint/str_replace/edit_region: the model picks exactly which
# renderings go into the contact sheet it gets back, instead of receiving a fixed set.
# Keep mutually-exclusive forms in separate branches. Some OpenAI-compatible providers
# materialize every optional property, producing invalid top-down+slice hybrids when the
# schema exposes all view fields in one loose object.
_YAW_SCHEMA = {
    "type": "integer",
    "minimum": 0,
    "maximum": 3,
    "description": "Camera rotation in 90-degree steps (0-3).",
}

_VIEW_PARAM = {
    "description": (
        "Choose exactly one shape. Use mode='iso' literally, not 'isometric'. A cutaway "
        "and a slice are mutually exclusive."
    ),
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode"],
            "properties": {"mode": {"const": "top-down"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode", "yaw"],
            "properties": {"mode": {"const": "iso"}, "yaw": _YAW_SCHEMA},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode", "yaw", "cutaway"],
            "properties": {
                "mode": {"const": "iso"},
                "yaw": _YAW_SCHEMA,
                "cutaway": {
                    "type": "string",
                    "enum": ["x", "z"],
                    "description": "Pair x with yaw 2/3, and z with yaw 1/2.",
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode", "yaw", "slice_axis", "slice_at"],
            "properties": {
                "mode": {"const": "iso"},
                "yaw": _YAW_SCHEMA,
                "slice_axis": {"type": "string", "enum": ["x", "y", "z"]},
                "slice_at": {"type": "integer", "description": "World coordinate of the slice plane."},
            },
        },
    ],
}

VIEWS_PARAM = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_VIEWS,
    "items": _VIEW_PARAM,
    "description": (
        "Which renderings to include in the contact sheet you'll get back after this build. "
        f"REQUIRED, 1-{MAX_VIEWS} entries — you get exactly what you ask for, nothing automatic. "
        'E.g. [{"mode": "iso", "yaw": 0}, '
        '{"mode": "iso", "yaw": 2, "cutaway": "x"}, {"mode": "top-down"}].'
    ),
}

SUBMIT_BLUEPRINT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_blueprint",
        "description": (
            "Validate, execute, and render a COMPLETE blueprint program, built from scratch "
            "into an empty world (it replaces any previous build). Use this to start over or "
            "make structural changes to the overall shape/footprint. For small incremental "
            "tweaks to an existing build, prefer str_replace or edit_region. On error you "
            "get a line-mapped traceback to fix. On success you get build stats and, in a "
            "follow-up message, a contact sheet of the views you requested to critique."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "code": {"type": "string", "description": "The full blueprint Python source."},
                "design_notes": {
                    "type": "string",
                    "description": "Brief notes on what this blueprint builds or what changed since last time.",
                },
                "views": VIEWS_PARAM,
            },
            "required": ["code", "design_notes", "views"],
        },
    },
}

STR_REPLACE_TOOL = {
    "type": "function",
    "function": {
        "name": "str_replace",
        "description": (
            "Incrementally edit the CURRENT build by find-and-replacing text in its accumulated "
            "blueprint source. Put the selected submitted-or-staged shape inside the required `edit` object. "
            "Like a coding agent's file-editing tool, `old_str` must match "
            "EXACTLY ONE location in the current source (whitespace and all) — include enough "
            "surrounding context (a few lines) to make the match unique; if it matches zero or "
            "multiple times you get an error and nothing changes. `new_str` replaces that match. "
            "If `submit` is true (default), the FULL resulting source is re-run from scratch and "
            "rendered — so, unlike a raw code delta, variables, helper functions, and transform "
            "contexts you defined elsewhere in the source stay intact — and this uses one edit "
            "from your budget. Set `submit` to false to stage the text edit WITHOUT building or "
            "rendering it (free, no budget used) so you can batch several str_replace calls — "
            "e.g. fix three unrelated spots — before spending a render on the combined result; "
            "the staged edits apply in order and the next str_replace/submit_blueprint call with "
            "submit=true (or the plain submit_blueprint tool) builds whatever has accumulated. "
            "If old_str isn't found, the error includes the closest matching lines, but if you're "
            "unsure of the exact current text, call query(request={'mode':'source'}) first to fetch fresh "
            "ground truth rather than guessing. On a submitted error the pre-edit build is left "
            "untouched and you get a line-mapped traceback against the patched source. On success "
            "you get updated stats and a contact sheet of the views you requested. Requires a "
            "prior successful submit_blueprint."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["edit"],
            "properties": {
                "edit": {
                    "description": "Choose a submitted edit with views or a free staged edit without views.",
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["old_str", "new_str", "submit", "design_notes", "views"],
                            "properties": {
                                "old_str": {
                                    "type": "string",
                                    "description": "Exact source text to replace; it must match exactly once.",
                                },
                                "new_str": {"type": "string"},
                                "submit": {"const": True},
                                "design_notes": {"type": "string"},
                                "views": VIEWS_PARAM,
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["old_str", "new_str", "submit", "design_notes"],
                            "properties": {
                                "old_str": {
                                    "type": "string",
                                    "description": "Exact source text to replace; it must match exactly once.",
                                },
                                "new_str": {"type": "string"},
                                "submit": {"const": False},
                                "design_notes": {"type": "string"},
                            },
                        },
                    ],
                }
            },
        },
    },
}

EDIT_REGION_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_region",
        "description": (
            "Rebuild one bounding-box region while freezing the rest of the build. The given "
            "region is cleared first, then your code runs against the current (post-clear) voxel "
            "state — so you can redo just the roof or one wing without risking regressions "
            "elsewhere. Your code runs against the EXISTING (post-clear) voxel state (not a "
            "fresh world): fresh transform stack each call, no persisted variables, pre-edit "
            "build untouched on error. Requires a prior successful submit_blueprint."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 6,
                    "maxItems": 6,
                    "description": "[x1, y1, z1, x2, y2, z2] bounding box to clear and rebuild.",
                },
                "code": {"type": "string", "description": "Blueprint snippet that rebuilds the region."},
                "design_notes": {"type": "string", "description": "Brief notes on what this edit changes."},
                "views": VIEWS_PARAM,
            },
            "required": ["region", "code", "design_notes", "views"],
        },
    },
}

INSPECT_TOOL = {
    "type": "function",
    "function": {
        "name": "inspect",
        "description": (
            "Re-render the current build without changing it, in one of two modes. FIXED-ANGLE "
            "Put the selected exact shape inside the required `view` object. "
            "(default): use yaw (0-3, 90-degree steps) and optionally a cutaway or slice for a "
            "quick isometric view. FREE-CAMERA: provide BOTH camera_pos and look_at ([x,y,z] in "
            "your blueprint's coordinate space) to view from an arbitrary position and angle — "
            "e.g. to inspect a facade up close, put camera_pos a few blocks out from it with "
            "look_at pointing at it. Providing camera_pos/look_at switches to free-camera mode."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["view"],
            "properties": {
                "view": {
                    "description": "Choose exactly one fixed, cutaway, slice, or free-camera view.",
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "yaw"],
                            "properties": {"mode": {"const": "iso"}, "yaw": _YAW_SCHEMA},
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "yaw", "cutaway"],
                            "properties": {
                                "mode": {"const": "iso"},
                                "yaw": _YAW_SCHEMA,
                                "cutaway": {"type": "string", "enum": ["x", "z"]},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "yaw", "slice_axis", "slice_at"],
                            "properties": {
                                "mode": {"const": "iso"},
                                "yaw": _YAW_SCHEMA,
                                "slice_axis": {"type": "string", "enum": ["x", "y", "z"]},
                                "slice_at": {"type": "integer"},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "camera_pos", "look_at"],
                            "properties": {
                                "mode": {"const": "camera"},
                                "camera_pos": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 3,
                                    "maxItems": 3,
                                },
                                "look_at": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 3,
                                    "maxItems": 3,
                                },
                            },
                        },
                    ],
                }
            },
        },
    },
}

QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "query",
        "description": (
            "Get lossless TEXT ground truth about the current build (no image). Modes: "
            "Put the selected exact shape inside the required `request` object. "
            "'slice' returns a one-char-per-block ASCII plan of a plane (use slice_axis + "
            "slice_at; slice_axis='y' gives a floor plan of that storey) with a material "
            "legend; 'point' returns the exact block at (x, y, z); 'histogram' returns material "
            "counts, optionally within a region; 'source' returns the full current blueprint "
            "source, line-numbered — use this instead of guessing at old_str when a str_replace "
            "call fails to match. Prefer this tool over inspect when you need to verify exact "
            "block placement or interior layout — text is more reliable than a small render."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["request"],
            "properties": {
                "request": {
                    "description": "Choose exactly one lossless query shape.",
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "slice_axis", "slice_at"],
                            "properties": {
                                "mode": {"const": "slice"},
                                "slice_axis": {"type": "string", "enum": ["x", "y", "z"]},
                                "slice_at": {"type": "integer"},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "x", "y", "z"],
                            "properties": {
                                "mode": {"const": "point"},
                                "x": {"type": "integer"},
                                "y": {"type": "integer"},
                                "z": {"type": "integer"},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode"],
                            "properties": {"mode": {"const": "histogram"}},
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode", "region"],
                            "properties": {
                                "mode": {"const": "histogram"},
                                "region": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 6,
                                    "maxItems": 6,
                                },
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["mode"],
                            "properties": {"mode": {"const": "source"}},
                        },
                    ],
                }
            },
        },
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Declare the build complete and end the session. Before finishing, you must have "
            "already called query(request={'mode':'slice', ...}) and seen a cutaway/slice of the CURRENT build "
            "(via a cutaway/slice entry in your latest build's `views`, or an inspect call); "
            "any subsequent edit resets both requirements."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string", "description": "A short summary of the finished build."},
            },
            "required": ["summary"],
        },
    },
}

ALL_TOOLS = [
    SUBMIT_BLUEPRINT_TOOL,
    STR_REPLACE_TOOL,
    EDIT_REGION_TOOL,
    INSPECT_TOOL,
    QUERY_TOOL,
    FINISH_TOOL,
]
