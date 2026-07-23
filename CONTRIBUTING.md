# Contributing

Create a Python 3.12 virtual environment and install `pip install -e .[dev]`. Before opening a change,
run `ruff check .`, `ruff format --check .`, and `pytest`.

Changes to canonical JSON must include a schema update, migration policy, and compatibility tests.
Never rewrite accepted fixtures or research artifacts to hide a breaking change. Security-sensitive
parser changes require malformed-input, resource-limit, path-safety, and prompt-injection tests.

New agent environments must use the canonical workflow and pass the same benchmark. Do not fork the
research logic into host-specific variants.

