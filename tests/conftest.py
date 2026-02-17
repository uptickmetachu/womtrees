from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_subprocess_generate_name():
    """Prevent _generate_name from calling 'claude -p' during tests."""
    with patch(
        "womtrees.cli.items._generate_name",
        side_effect=lambda prompt: prompt[:40].lower().replace(" ", "-"),
    ):
        yield
