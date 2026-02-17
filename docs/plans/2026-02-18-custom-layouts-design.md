# Custom Tmux Layouts

## Problem

womtrees hardcodes a two-pane layout (Claude | Terminal). Different projects need different layouts — a frontend repo might want a dev server pane, a backend repo might want a log tail or DB console.

## Design

### Named Layout Presets

Layouts are defined as named presets in `~/.config/womtrees/config.toml`. Each layout has one or more windows, each window has an ordered list of panes and a tmux layout string.

```toml
[tmux]
default_layout = "standard"

[layouts.standard]
[[layouts.standard.windows]]
name = "main"
layout = "even-horizontal"
panes = [
  { claude = true },
  {},
]

[layouts.l-shape]
[[layouts.l-shape.windows]]
name = "main"
layout = "main-vertical"
panes = [
  { claude = true },
  {},
  { command = "tail -f logs/dev.log" },
]

[layouts.dev-server]
[[layouts.dev-server.windows]]
name = "code"
layout = "even-horizontal"
panes = [
  { claude = true },
  {},
]
[[layouts.dev-server.windows]]
name = "services"
layout = "even-horizontal"
panes = [
  { command = "npm run dev" },
  { command = "npm run test -- --watch" },
]
```

### Per-Project Layout Selection

Projects reference a layout by name in `.womtrees.toml`:

```toml
layout = "dev-server"
```

### Layout Resolution Order

1. `.womtrees.toml` `layout` field (project-specific)
2. `config.toml` `tmux.default_layout` (global default)
3. `"standard"` (hardcoded fallback)

### Pane Definition

Each pane is a TOML inline table with optional fields:

| Field     | Type   | Default | Description                          |
|-----------|--------|---------|--------------------------------------|
| `claude`  | bool   | false   | Marks this pane as the Claude pane   |
| `command` | string | —       | Command to run via `send-keys`       |

A pane with no fields (`{}`) is a plain shell. Exactly one pane across all windows must have `claude = true`.

### Window Layout String

The `layout` field on each window accepts:

- **tmux built-in names**: `even-horizontal`, `even-vertical`, `main-horizontal`, `main-vertical`, `tiled`
- **Raw tmux layout strings**: e.g., `"a]a0,208x54,0,0{104x54,0,0,105x54,105,0}"` for precise custom geometry

After all panes in a window are created, `tmux select-layout -t <window> <layout>` is called. Panes are assigned in the order listed (left-to-right, top-to-bottom).

### Backward Compatibility

If no `[layouts]` section exists in `config.toml`, a `"standard"` layout is synthesized from the existing `tmux.split` and `tmux.claude_pane` fields:

- `split = "vertical"` + `claude_pane = "left"` → `even-horizontal` with Claude first, shell second
- `split = "vertical"` + `claude_pane = "right"` → `even-horizontal` with shell first, Claude second
- `split = "horizontal"` + `claude_pane = "top"` → `even-vertical` with Claude first, shell second
- `split = "horizontal"` + `claude_pane = "bottom"` → `even-vertical` with shell first, Claude second

Once a user adds `[layouts]`, the old `tmux.split`/`tmux.claude_pane` fields are ignored.

### Validation

At config load time:

- Each layout must have at least one window
- Each window must have at least one pane
- Exactly one pane across all windows must have `claude = true`
- A pane cannot have both `claude = true` and `command` set

## Implementation

### Phase 1: Config Parsing

**`config.py`** — New dataclasses:

```python
@dataclass
class PaneConfig:
    claude: bool = False
    command: str | None = None

@dataclass
class WindowConfig:
    name: str
    layout: str = "even-horizontal"
    panes: list[PaneConfig]

@dataclass
class LayoutConfig:
    windows: list[WindowConfig]
```

Add to `Config`:

```python
layouts: dict[str, LayoutConfig]
default_layout: str
```

Parse `[layouts.*]` sections from TOML. Synthesize `"standard"` from legacy fields if no layouts defined.

### Phase 2: Tmux Functions

**`tmux.py`** — Add:

```python
def new_window(session: str, name: str, working_dir: str) -> str:
    """Create a new window in an existing session. Returns pane_id."""

def select_layout(target: str, layout: str) -> None:
    """Apply a tmux layout to a window target."""
```

Existing functions (`create_session`, `split_pane`, `send_keys`) remain unchanged.

### Phase 3: Workitem Service

**`services/workitem.py`** — Refactor `start_work_item()`:

```python
def start_work_item(conn, item_id, config):
    # ... existing worktree creation ...

    # Resolve layout
    layout = resolve_layout(item.repo_path, config)

    # Create tmux session (first window's first pane comes free)
    session_name, first_pane_id = tmux.create_session(...)
    tmux.set_environment(...)

    claude_pane_id = None
    for win_idx, window in enumerate(layout.windows):
        if win_idx == 0:
            # First window already exists from create_session
            current_pane_id = first_pane_id
        else:
            current_pane_id = tmux.new_window(session_name, window.name, str(wt_path))

        pane_ids = [current_pane_id]
        for _ in window.panes[1:]:
            pane_id = tmux.split_pane(session_name, "vertical", str(wt_path))
            pane_ids.append(pane_id)

        # Apply layout after all panes exist
        window_target = f"{session_name}:{window.name}"
        tmux.select_layout(window_target, window.layout)

        # Send commands
        for pane_cfg, pane_id in zip(window.panes, pane_ids):
            if pane_cfg.claude:
                claude_pane_id = pane_id
                tmux.send_keys(pane_id, build_claude_cmd(config, item))
            elif pane_cfg.command:
                tmux.send_keys(pane_id, pane_cfg.command)

    # Create ClaudeSession with claude_pane_id
    # Update work item status
```

Add layout resolution helper:

```python
def resolve_layout(repo_path: str, config: Config) -> LayoutConfig:
    """Resolve layout: .womtrees.toml → config default → 'standard'."""
    project_config = load_womtrees_config(repo_path)
    layout_name = (project_config or {}).get("layout", config.default_layout)
    if layout_name not in config.layouts:
        raise ValueError(f"Layout '{layout_name}' not found in config")
    return config.layouts[layout_name]
```

### No DB Changes

The `claude_sessions` table already stores a pane ID — that still works. Extra panes are just tmux panes with no DB tracking.
