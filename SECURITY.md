# Security policy

## Reporting a vulnerability

Open a GitHub security advisory on the repository, or email the maintainers. Please do not open a
public issue for an unpatched vulnerability.

Useful reports include: the input that triggers it (a synthesized reproducer is ideal — do not
send confidential documents), the observed behaviour, and what boundary you believe it crosses.

## Scope

In scope:

- Writing outside the workspace root by any route (traversal, symlink, archive entry, crafted
  filename)
- Executing content from an imported document
- Any network request made by core processing
- Bypassing a report gate so an unsupported claim reaches a published report
- Artifact tampering that `artifact_hash` verification fails to detect
- Denial of service through a crafted PDF or Markdown file

Out of scope, by design — see `docs/security-model.md`:

- Vulnerabilities in your host agent or its model provider
- A compromised agent writing bad artifacts (the gates bound this; they cannot prevent it)
- Absence of workspace encryption at rest
- Absence of authentication (this is a single-user local tool)
- Hash verification not being cryptographic signing

## Handling untrusted documents

PDF parsing runs in-process and is not sandboxed. Import only documents you are willing to parse.
If you must handle genuinely hostile input, run the CLI in a container or VM.
