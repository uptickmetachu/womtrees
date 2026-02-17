from __future__ import annotations

import pytest

from womtrees.config import (
    LayoutConfig,
    PaneConfig,
    WindowConfig,
    _parse_layouts,
    _synthesize_standard_layout,
    _validate_layout,
)


# -- Parsing --


def test_parse_single_window_layout() -> None:
    data = {
        "layouts": {
            "standard": {
                "windows": [
                    {
                        "name": "main",
                        "layout": "even-horizontal",
                        "panes": [
                            {"claude": True},
                            {},
                        ],
                    }
                ]
            }
        }
    }
    layouts = _parse_layouts(data)
    assert "standard" in layouts
    layout = layouts["standard"]
    assert len(layout.windows) == 1
    win = layout.windows[0]
    assert win.name == "main"
    assert win.layout == "even-horizontal"
    assert len(win.panes) == 2
    assert win.panes[0].claude is True
    assert win.panes[0].command is None
    assert win.panes[1].claude is False
    assert win.panes[1].command is None


def test_parse_multi_window_layout() -> None:
    data = {
        "layouts": {
            "dev-server": {
                "windows": [
                    {
                        "name": "code",
                        "layout": "even-horizontal",
                        "panes": [{"claude": True}, {}],
                    },
                    {
                        "name": "services",
                        "layout": "even-vertical",
                        "panes": [
                            {"command": "npm run dev"},
                            {"command": "npm run test"},
                        ],
                    },
                ]
            }
        }
    }
    layouts = _parse_layouts(data)
    layout = layouts["dev-server"]
    assert len(layout.windows) == 2
    assert layout.windows[0].name == "code"
    assert layout.windows[1].name == "services"
    assert layout.windows[1].panes[0].command == "npm run dev"
    assert layout.windows[1].panes[1].command == "npm run test"


def test_parse_empty_layouts() -> None:
    layouts = _parse_layouts({})
    assert layouts == {}


def test_parse_pane_defaults() -> None:
    data = {
        "layouts": {
            "minimal": {
                "windows": [
                    {
                        "panes": [{"claude": True}],
                    }
                ]
            }
        }
    }
    layouts = _parse_layouts(data)
    win = layouts["minimal"].windows[0]
    assert win.name == "main"  # default
    assert win.layout == "even-horizontal"  # default


# -- Backward compat synthesis --


def test_synthesize_vertical_left() -> None:
    layout = _synthesize_standard_layout("vertical", "left")
    assert len(layout.windows) == 1
    win = layout.windows[0]
    assert win.layout == "even-horizontal"
    assert win.panes[0].claude is True
    assert win.panes[1].claude is False


def test_synthesize_vertical_right() -> None:
    layout = _synthesize_standard_layout("vertical", "right")
    win = layout.windows[0]
    assert win.layout == "even-horizontal"
    assert win.panes[0].claude is False
    assert win.panes[1].claude is True


def test_synthesize_horizontal_top() -> None:
    layout = _synthesize_standard_layout("horizontal", "top")
    win = layout.windows[0]
    assert win.layout == "even-vertical"
    assert win.panes[0].claude is True


def test_synthesize_horizontal_bottom() -> None:
    layout = _synthesize_standard_layout("horizontal", "bottom")
    win = layout.windows[0]
    assert win.layout == "even-vertical"
    assert win.panes[0].claude is False
    assert win.panes[1].claude is True


# -- Validation --


def test_validate_no_claude_pane() -> None:
    layout = LayoutConfig(
        windows=[WindowConfig(name="main", panes=[PaneConfig(), PaneConfig()])]
    )
    with pytest.raises(ValueError, match="exactly one pane with claude=true"):
        _validate_layout("bad", layout)


def test_validate_multiple_claude_panes() -> None:
    layout = LayoutConfig(
        windows=[
            WindowConfig(
                name="main",
                panes=[PaneConfig(claude=True), PaneConfig(claude=True)],
            )
        ]
    )
    with pytest.raises(ValueError, match="2 claude panes"):
        _validate_layout("bad", layout)


def test_validate_claude_with_command() -> None:
    layout = LayoutConfig(
        windows=[
            WindowConfig(
                name="main",
                panes=[PaneConfig(claude=True, command="echo hi")],
            )
        ]
    )
    with pytest.raises(ValueError, match="cannot have both claude=true and command"):
        _validate_layout("bad", layout)


def test_validate_empty_windows() -> None:
    layout = LayoutConfig(windows=[])
    with pytest.raises(ValueError, match="at least one window"):
        _validate_layout("bad", layout)


def test_validate_empty_panes() -> None:
    layout = LayoutConfig(windows=[WindowConfig(name="main", panes=[])])
    with pytest.raises(ValueError, match="at least one pane"):
        _validate_layout("bad", layout)


def test_validate_valid_layout() -> None:
    layout = LayoutConfig(
        windows=[
            WindowConfig(
                name="main",
                panes=[PaneConfig(claude=True), PaneConfig()],
            )
        ]
    )
    # Should not raise
    _validate_layout("good", layout)
