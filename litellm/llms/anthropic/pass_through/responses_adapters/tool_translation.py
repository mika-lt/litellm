import re
from collections.abc import Mapping, Sequence
from typing import Final

_VERSIONED_TOOL_TYPE: Final = re.compile(r"(?P<family>[a-z0-9_]+?)_(?P<version>\d{8})")
_TEXT_EDITOR_INSERT_TEXT_SINCE: Final = "20250429"
_COMPUTER_MODIFIERS_SINCE: Final = "20250124"
_COMPUTER_ZOOM_SINCE: Final = "20251124"
_COMPUTER_ACTIONS_20241022: Final = (
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "screenshot",
    "cursor_position",
)
_COMPUTER_ACTIONS_20250124: Final = (
    *_COMPUTER_ACTIONS_20241022,
    "left_mouse_down",
    "left_mouse_up",
    "scroll",
    "hold_key",
    "wait",
    "triple_click",
)
_COMPUTER_ACTIONS_20251124: Final = (*_COMPUTER_ACTIONS_20250124, "zoom")


def _string(description: str) -> Mapping[str, object]:
    return {"type": "string", "description": description}


def _integer(description: str) -> Mapping[str, object]:
    return {"type": "integer", "description": description}


def _integers(count: int, description: str) -> Mapping[str, object]:
    return {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": count,
        "maxItems": count,
        "description": description,
    }


def _enum(values: Sequence[str]) -> Mapping[str, object]:
    return {"type": "string", "enum": list(values)}


def _function(
    name: str, description: str, properties: Mapping[str, object], required: Sequence[str]
) -> Mapping[str, object]:
    return {
        "type": "function",
        "name": name,
        "strict": False,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)},
    }


def _bash_tool(name: str) -> Mapping[str, object]:
    return _function(
        name,
        "Run a command in a persistent bash session. The working directory, environment, and files carry over "
        "between calls.",
        {
            "command": _string("The bash command to run. Required unless restart is true."),
            "restart": {"type": "boolean", "description": "Set to true to restart the bash session."},
        },
        (),
    )


def _text_editor_tool(name: str, version: str) -> Mapping[str, object]:
    inserts_insert_text: Final = version >= _TEXT_EDITOR_INSERT_TEXT_SINCE
    edit_properties: Final[Mapping[str, object]] = {
        "command": _enum(
            ("view", "create", "str_replace", "insert")
            if inserts_insert_text
            else ("view", "create", "str_replace", "insert", "undo_edit")
        ),
        "path": _string("Absolute path to the file or directory."),
        "view_range": _integers(2, "Optional [start, end] line numbers for view. An end of -1 reads to the end."),
        "file_text": _string("Content of the new file, for create."),
        "old_str": _string("Exact text to replace, for str_replace. It must match exactly one place in the file."),
        "new_str": _string(
            "Replacement text, for str_replace."
            if inserts_insert_text
            else "Replacement text for str_replace, or the text to add for insert."
        ),
        "insert_line": _integer("Line number to insert after, for insert. 0 inserts at the start of the file."),
    }
    return _function(
        name,
        "View, create, and edit text files. view lists a directory or shows a file with line numbers.",
        (
            {**edit_properties, "insert_text": _string("Text to add, for insert.")}
            if inserts_insert_text
            else edit_properties
        ),
        ("command", "path"),
    )


def _memory_tool(name: str) -> Mapping[str, object]:
    return _function(
        name,
        "Read and write files in the /memories directory, which persists between conversations. View it before "
        "starting a task, and record progress and learnings as you work.",
        {
            "command": _enum(("view", "create", "str_replace", "insert", "delete", "rename")),
            "path": _string("Path under /memories, for every command but rename."),
            "view_range": _integers(2, "Optional [start, end] line numbers for view."),
            "file_text": _string("Content of the new file, for create."),
            "old_str": _string("Exact text to replace, for str_replace."),
            "new_str": _string("Replacement text, for str_replace."),
            "insert_line": _integer("Line number to insert after, for insert."),
            "insert_text": _string("Text to add, for insert."),
            "old_path": _string("Current path, for rename."),
            "new_path": _string("New path, for rename."),
        },
        ("command",),
    )


def _computer_properties(version: str, zoom: bool) -> Mapping[str, object]:
    pointer: Final[Mapping[str, object]] = {
        "text": _string("Text to type for type, or keys to press for key and hold_key, such as ctrl+s."),
        "coordinate": _integers(2, "[x, y] pixel position for a click, mouse_move, or the end of left_click_drag."),
        "start_coordinate": _integers(2, "[x, y] pixel position where left_click_drag starts."),
    }
    if version < _COMPUTER_MODIFIERS_SINCE:
        return {"action": _enum(_COMPUTER_ACTIONS_20241022), **pointer}
    modifiers: Final[Mapping[str, object]] = {
        **pointer,
        "scroll_direction": _enum(("up", "down", "left", "right")),
        "scroll_amount": _integer("Number of scroll steps, for scroll."),
        "text": _string(
            "Text to type for type, keys to press for key and hold_key, such as ctrl+s, or a modifier key to hold "
            "during scroll, such as shift."
        ),
        "duration": {"type": "number", "description": "Seconds to wait for wait, or to hold for hold_key."},
        "key": _string("Modifier key to hold during a click, such as shift."),
    }
    if not zoom:
        return {"action": _enum(_COMPUTER_ACTIONS_20250124), **modifiers}
    return {
        "action": _enum(_COMPUTER_ACTIONS_20251124),
        **modifiers,
        "region": _integers(4, "[x0, y0, x1, y1] screen region to show at full resolution, for zoom."),
    }


def _computer_tool(name: str, version: str, tool: Mapping[str, object]) -> Mapping[str, object]:
    width: Final = tool.get("display_width_px")
    height: Final = tool.get("display_height_px")
    display: Final = (
        f"a {width}x{height} pixel display" if isinstance(width, int) and isinstance(height, int) else "a display"
    )
    return _function(
        name,
        f"Control {display} with the mouse and keyboard, and take screenshots to see it. Coordinates are pixels "
        "from the top left.",
        _computer_properties(version, zoom=version >= _COMPUTER_ZOOM_SINCE and tool.get("enable_zoom") is True),
        ("action",),
    )


def typed_client_tool(tool: Mapping[str, object]) -> Mapping[str, object] | None:
    tool_type: Final = tool.get("type")
    name: Final = tool.get("name")
    if not isinstance(tool_type, str) or not isinstance(name, str):
        return None
    versioned: Final = _VERSIONED_TOOL_TYPE.fullmatch(tool_type)
    if versioned is None:
        return None
    version: Final = versioned["version"]
    match versioned["family"]:
        case "bash":
            return _bash_tool(name)
        case "text_editor":
            return _text_editor_tool(name, version)
        case "memory":
            return _memory_tool(name)
        case "computer":
            return _computer_tool(name, version, tool)
        case _:
            return None
