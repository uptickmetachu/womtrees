from __future__ import annotations

import os
import subprocess

import click

from womtrees.config import ensure_config, get_config


@click.command()
@click.option(
    "--dialog",
    type=click.Choice(["todo", "create"]),
    default=None,
    help="Open a specific dialog instead of the full board.",
)
@click.option("--repo", default=None, help="Repository path (for dialog mode).")
def board(dialog: str | None, repo: str | None) -> None:
    """Open the kanban board TUI."""
    from womtrees.tui.app import WomtreesApp

    app = WomtreesApp(dialog=dialog, repo_override=repo)
    app.run()


@click.command("sqlite")
def sqlite_cmd() -> None:
    """Open the womtrees database in sqlite3."""
    config = get_config()
    db_path = config.base_dir / "womtrees.db"
    subprocess.run(["sqlite3", str(db_path)])


@click.group("self")
def self_cmd() -> None:
    """Manage the womtrees installation itself."""


@self_cmd.command("update")
def self_update() -> None:
    """Update womtrees to the latest version via uv tool upgrade."""
    package = "womtrees"
    click.echo(f"Updating {package}...")
    result = subprocess.run(
        ["uv", "tool", "upgrade", package],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo(result.stdout.strip() or "Already up to date.")
    else:
        # uv tool upgrade fails if not installed via uv tool — hint the user
        click.echo(f"Update failed (exit {result.returncode}):", err=True)
        if result.stderr:
            click.echo(result.stderr.strip(), err=True)
        click.echo(
            "Hint: self update requires womtrees to be installed via "
            "'uv tool install'.",
            err=True,
        )
        raise SystemExit(1)


@click.command()
@click.option("--edit", is_flag=True, help="Open config in $EDITOR.")
def config(edit: bool) -> None:
    """View or edit configuration."""
    config_path = ensure_config()

    if edit:
        editor = os.environ.get("EDITOR", "vi")
        subprocess.run([editor, str(config_path)])
    else:
        click.echo(config_path.read_text())
