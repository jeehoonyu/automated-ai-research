"""Runtime data must live inside the package.

WHY THIS FILE EXISTS. `SCHEMA_ROOT` was `Path(__file__).resolve().parents[3] / "schemas"` — the
repository root. That path exists in a source checkout and in an editable install, so the whole test
suite was green while the built wheel shipped no schemas at all. An installed copy could run
`--version` and `init`, and every command past those raised "schema file is missing".

The CI job meant to catch that ran exactly `--version` and `init`.

These tests do not need CI, a network, or a build. They assert the property directly: every file the
code loads at runtime resolves inside `src/research/`, and every such directory is covered by a
`package-data` glob in pyproject.toml. A future `assets/`-style directory added without a glob fails
here rather than in someone's `pip install`.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

import research
from research.artifacts.registry import SCHEMA_ROOT, known_schemas
from research.profiles import PACKAGED_PROFILE_DIR

PACKAGE_ROOT = Path(research.__file__).resolve().parent
REPO = PACKAGE_ROOT.parents[1]

# Every directory of non-Python files the package reads at runtime.
RUNTIME_DATA_DIRS = [
    PACKAGE_ROOT / "schemas" / "v1",
    PACKAGE_ROOT / "profiles",
    PACKAGE_ROOT / "assets",
    PACKAGE_ROOT / "reporting" / "templates",
]


def _package_data_globs() -> list[str]:
    with open(REPO / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["setuptools"]["package-data"]["research"]


@pytest.mark.parametrize("directory", RUNTIME_DATA_DIRS, ids=lambda p: p.name)
def test_runtime_data_lives_inside_the_package(directory: Path):
    assert directory.is_dir(), f"{directory} is missing"
    assert PACKAGE_ROOT in directory.parents or directory == PACKAGE_ROOT, \
        f"{directory} is outside the package, so no wheel can ship it"


def test_the_schema_root_is_inside_the_package():
    """The specific regression. `parents[3]` walked out of the package and into the repository."""
    assert SCHEMA_ROOT.is_relative_to(PACKAGE_ROOT), (
        f"SCHEMA_ROOT is {SCHEMA_ROOT}, which is not under {PACKAGE_ROOT}. An installed wheel "
        f"cannot contain it, so every artifact write would fail.")


@pytest.mark.parametrize("directory", RUNTIME_DATA_DIRS, ids=lambda p: p.name)
def test_every_runtime_data_file_is_covered_by_a_package_data_glob(directory: Path):
    """A file present in the repository but absent from `package-data` is absent from the wheel."""
    globs = _package_data_globs()
    uncovered = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix == ".py":
            continue
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        if not any(fnmatch(relative, pattern) for pattern in globs):
            uncovered.append(relative)
    assert not uncovered, (
        f"{uncovered} would not be installed. Add a glob to [tool.setuptools.package-data] in "
        f"pyproject.toml.")


def test_every_registered_schema_resolves():
    """Not "the directory exists" — every schema the registry claims to know actually loads."""
    from research.artifacts.registry import _load

    for name in known_schemas():
        assert _load(name)["title"], name


def test_the_shipped_profiles_resolve():
    names = sorted(p.stem for p in PACKAGED_PROFILE_DIR.glob("*.yaml"))
    assert "default" in names and "medicine" in names, names
