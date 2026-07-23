from __future__ import annotations

from pathlib import Path

import pytest

from research.workspace import init_workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    init_workspace(target)
    return target
