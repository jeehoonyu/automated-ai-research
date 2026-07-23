# Security policy

Report vulnerabilities privately to the repository maintainers rather than publishing an exploit.

The MVP treats PDFs, Markdown, metadata, filenames, links, and agent responses as untrusted. Core
processing makes no network requests and never executes document content. Imports reject symlinks,
limit file size, sanitize display names, and restrict generated writes to the workspace.

PDF parsers process complex untrusted input and may contain upstream vulnerabilities. Keep dependencies
patched, process sensitive corpora in an OS-level sandbox, and do not assume this package replaces
endpoint isolation. OCR, archive extraction, browser automation, and embedded model execution are not
part of the MVP.

