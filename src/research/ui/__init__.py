"""`research ui` — a local, read-only view of a workspace.

WHY A UI AT ALL. Everything here is already available from the CLI. What a browser adds is the one
thing a terminal is bad at: following a chain. A published claim rests on evidence, which rests on a
locator, which resolves into immutable source bytes, and checking that chain by hand means four
`research inspect` invocations and a lot of copied identifiers. Here it is four clicks.

THREE RULES, AND THEY ARE NOT NEGOTIABLE.

1. **It cannot write.** No route mutates a workspace. The server answers GET and HEAD and refuses
   every other method. This is not a convenience choice — a UI that could edit a canonical artifact
   would be a path around the hash chain, the promotion gate, and the amendment record all at once.
   `research search --run` records retrieval provenance; the UI's search deliberately does not,
   because recording is a write.

2. **It cannot make a gate look better than it is.** The status vocabulary is imported from
   `validation.validator`, and the "does this block" question is answered by `CheckResult.blocks`
   itself rather than by a mapping written out again here. `not_evaluated` is therefore styled
   exactly as `failed` is, because it blocks exactly as `failed` does. A dashboard that renders
   "nobody looked" as a calm grey is the same failure this project keeps finding in its own gates,
   moved to the presentation layer.

3. **It treats document text as data.** Imported bytes reach the browser on several of these pages.
   Templates autoescape, the response carries a content-security policy that permits no script from
   any origin, and every block of document-derived text is labelled as untrusted in the page itself.

BOUND TO LOOPBACK. The UI exposes full document text and every artifact in the workspace, and it has
no authentication of any kind. It refuses to bind to a non-loopback address unless told to, and it
rejects requests whose `Host` header is not loopback so that a hostile page cannot reach it by
rebinding DNS.
"""

from __future__ import annotations

from .server import DEFAULT_HOST, DEFAULT_PORT, serve

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "serve"]
