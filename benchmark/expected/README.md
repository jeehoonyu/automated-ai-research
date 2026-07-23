# Benchmark expectations

The deterministic checks require exact citation resolution, discovery of the seeded contradiction,
inert handling of prompt-injection text, and an explicit limitation against generalizing the synthetic
result. Host conformance artifacts belong in `benchmark/expected/codex/` and
`benchmark/expected/claude-code/`; they are validated by the same schemas and report gates.

Use `python benchmark/prepare_conformance.py <output>` before a new qualification. It prepares both
the conflicting-evidence and insufficient-evidence runs from one canonical source/index base, records
a hash of the preparation manifest, and verifies semantic packet parity across hosts.
