# Automated AI Research Platform

An open-source, local-first toolkit for evidence-first research with Codex, Claude Code, and
other repository-capable coding agents. The package performs deterministic document processing,
full-text search, typed artifact management, citation resolution, validation, and report gating.
The host coding agent performs research reasoning; this project does not embed or launch a model.

## What it does

- Preserves PDF and Markdown originals by SHA-256 identity.
- Extracts page-aware text and renders every PDF page for visual verification.
- Flags image-only and low-text pages instead of silently treating them as extracted.
- Builds a rebuildable, integrity-checked SQLite FTS5 index with stable result ordering.
- Creates typed work packets shared by Codex and Claude Code.
- Validates evidence locators, claims, reviews, amendments, hashes, and lifecycle transitions.
- Produces Markdown reports only from canonical, validated JSON artifacts.

Version 1 does not browse the web, download URLs, run model APIs, host local models, perform OCR,
use embeddings, or provide a graphical interface.

## Development installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
research --help
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Quick start

```bash
research init example-workspace
cd example-workspace
research import ./sources
research index
research search "research question"
research run --question "research question" --profile default --host codex
```

Open the workspace in Codex or Claude Code. The host reads `AGENTS.md` or `CLAUDE.md`, then follows
the canonical work packets under `runs/<run-id>/packets/`. Candidate stage JSON belongs under
`runs/<run-id>/responses/<stage>/` and becomes canonical only after stage validation.

```bash
research validate <run-id> --stage planning
research status <run-id>
research validate <run-id>
research report <run-id>
```

Use `research report <run-id> --draft` for an explicitly unvalidated draft. Publication is blocked
when citations, reviews, independence, source hashes, locators, or human-review gates fail.
Human review and amendment artifacts must explicitly identify a human actor; host-agent output cannot
silently clear a human gate.

## Authority and trust

1. Original files are authoritative evidence.
2. Content hashes establish original identity.
3. Versioned JSON artifacts are canonical research state.
4. Valid locators connect evidence to originals.
5. Validation determines report eligibility.
6. Markdown reports are derived views.

Imported content is untrusted. The platform never executes commands, follows links, or changes its
workflow based on document text. JSON artifacts contain concise findings and citations, never hidden
chain-of-thought.

See [architecture](docs/architecture.md), [workflow](docs/workflow.md),
[artifact contracts](docs/artifact-contracts.md), [validation rules](docs/validation-rules.md), and
the [security model](docs/security-model.md). Release qualification, including separate host and
human-review gates, is tracked in the [release checklist](docs/release-checklist.md), with current
evidence and open external gates in the [completion audit](docs/completion-audit.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
