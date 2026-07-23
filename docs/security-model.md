# Security model

Trusted inputs are repository workflow files, installed schemas, explicit CLI arguments, and local
configuration controlled by the user. Imported documents and agent-produced candidates are untrusted.

The core has no network client. Markdown links are metadata only. PDF content, HTML, scripts, macros,
shell text, and prompt-like passages remain data. Work packets visibly separate trusted instructions
from untrusted source content.

Generated writes are contained beneath the resolved workspace root and use same-directory temporary
files plus atomic replacement. Import reads may originate outside the workspace, but symlinks and
non-regular files are rejected. Original filenames are metadata, never storage paths. Logs must be
secret-free and are never evidence.

Limits do not make PDF parsing risk-free. Use OS isolation for hostile corpora and review upstream parser
advisories. Automatic URL fetching, archives, OCR, model processes, and document command execution are
deliberately absent.

