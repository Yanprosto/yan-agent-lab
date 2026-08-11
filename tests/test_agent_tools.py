from typing import Any, cast

from mcbuild.agent import tools


def _assert_no_defaults(value):
    if isinstance(value, dict):
        assert "default" not in value
        for item in value.values():
            _assert_no_defaults(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_defaults(item)


def test_build_view_schema_uses_mutually_exclusive_exact_shapes():
    views_param = cast(dict[str, Any], tools.VIEWS_PARAM)
    branches = cast(list[dict[str, Any]], views_param["items"]["oneOf"])

    assert [branch["required"] for branch in branches] == [
        ["mode"],
        ["mode", "yaw"],
        ["mode", "yaw", "cutaway"],
        ["mode", "yaw", "slice_axis", "slice_at"],
    ]
    assert all(branch["additionalProperties"] is False for branch in branches)
    assert [branch["properties"]["mode"] for branch in branches] == [
        {"const": "top-down"},
        {"const": "iso"},
        {"const": "iso"},
        {"const": "iso"},
    ]
    _assert_no_defaults(tools.VIEWS_PARAM)


def test_mode_dependent_tools_do_not_expose_incompatible_optional_fields_together():
    inspect_tool = cast(dict[str, Any], tools.INSPECT_TOOL)
    inspect_branches = cast(
        list[dict[str, Any]],
        inspect_tool["function"]["parameters"]["properties"]["view"]["oneOf"],
    )
    assert [set(branch["properties"]) for branch in inspect_branches] == [
        {"mode", "yaw"},
        {"mode", "yaw", "cutaway"},
        {"mode", "yaw", "slice_axis", "slice_at"},
        {"mode", "camera_pos", "look_at"},
    ]

    query_tool = cast(dict[str, Any], tools.QUERY_TOOL)
    query_branches = cast(
        list[dict[str, Any]],
        query_tool["function"]["parameters"]["properties"]["request"]["oneOf"],
    )
    assert [branch["properties"]["mode"]["const"] for branch in query_branches] == [
        "slice",
        "point",
        "histogram",
        "histogram",
        "source",
    ]
    assert all(branch["additionalProperties"] is False for branch in query_branches)

    replace_tool = cast(dict[str, Any], tools.STR_REPLACE_TOOL)
    replace_branches = cast(
        list[dict[str, Any]],
        replace_tool["function"]["parameters"]["properties"]["edit"]["oneOf"],
    )
    assert replace_branches[0]["properties"]["submit"] == {"const": True}
    assert "views" in replace_branches[0]["properties"]
    assert replace_branches[1]["properties"]["submit"] == {"const": False}
    assert "views" not in replace_branches[1]["properties"]


def test_every_agent_tool_schema_rejects_unknown_top_level_arguments():
    all_tools = cast(list[dict[str, Any]], tools.ALL_TOOLS)
    for tool in all_tools:
        parameters = tool["function"]["parameters"]
        assert parameters["additionalProperties"] is False
        assert "properties" in parameters
        _assert_no_defaults(parameters)
