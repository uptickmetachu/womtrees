from __future__ import annotations

import os
import subprocess

import click

from womtrees.config import ensure_config, get_config


@click.command()
def board() -> None:
    """Open the kanban board TUI."""
    from womtrees.tui.app import WomtreesApp

    app = WomtreesApp()
    app.run()


@click.command("sqlite")
def sqlite_cmd() -> None:
    """Open the womtrees database in sqlite3."""
    config = get_config()
    db_path = config.base_dir / "womtrees.db"
    subprocess.run(["sqlite3", str(db_path)])


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
