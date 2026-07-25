"""Automated AI Research Platform.

Local-first, evidence-first. This package performs deterministic document processing, indexing,
search, state management, validation, gating, and report rendering. It deliberately contains no
model provider, no agent framework, and no network access in core processing: the host environment
(Codex, Claude Code, or another) supplies the reasoning through work packets.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
