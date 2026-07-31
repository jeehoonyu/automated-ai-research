# Orientation for AI tools

You are working in **automated-ai-research**, the repository — the tool itself. Read this before
touching anything; it is written to be the only file you need in order to know where things are and
what must not break.

> **There is a second `AGENTS.md`, and it is not this one.** `research init` writes one into every
> workspace it creates, pointing at that workspace's copy of the canonical workflow. That file is
> about *conducting research*; this file is about *the code that checks it*. If you are reading this
> from inside a directory containing `research.yaml`, you have the wrong file — read the one beside
> it.

It is tool-agnostic on purpose. Codex, Claude Code, Cursor, Aider and anything else read the same
file, for the same reason the research workflow itself has no host-specific logic: two tools with two
sets of rules quietly become two standards of evidence.

---

## 1. The one thing to understand first

**There are two trees, and confusing them causes most mistakes.**

| | The repository | A workspace |
|---|---|---|
| What it is | the tool — deterministic Python that checks things | your data — a corpus, and research runs over it |
| Created by | `git clone` | `research init <path>` |
| Contains | `src/`, `tests/`, `docs/`, `benchmark/` | `research.yaml`, `documents/`, `indexes/`, `runs/` |
| Who writes it | you, editing code | the CLI and your research agent |
| Lives | wherever you cloned it | **anywhere else** — never inside the repository |

If the task is "help me research something", you want a **workspace** and section 4.
If the task is "change how the tool behaves", you want the **repository** and section 5.

The package performs **no network requests** in core processing. There is no model API, no agent
framework, no vector database, and no web fetch anywhere in import, extraction, indexing, search,
validation or reporting. That is an architectural boundary, not a missing feature. The intelligence
comes from *you*, the host agent; this repository supplies the parts that make your output checkable.

---

## 2. What the repository is for, in one paragraph

You point it at PDFs and Markdown. It preserves the originals byte-for-byte, extracts and indexes
them, and hands your agent structured **work packets**. Your agent does the reasoning. The package
does the parts that must be deterministic: hashing, extraction, indexing, search, run state,
validation, citation resolution, publication gating, and report rendering.

> **The point is not to produce a report. It is to refuse to produce one that isn't supported.**

Everything below follows from that sentence. When a change would make it less true, the change is
wrong even if it makes something else better.

---

## 3. Folder map

### The tool

| Path | What lives here | Touch it when |
|---|---|---|
| `src/research/` | the whole package | changing behaviour |
| `src/research/cli.py` | every command; thin, delegates immediately | adding a command or a flag |
| `src/research/artifacts/` | canonical JSON envelope, schema registry, locators | changing what an artifact is |
| `src/research/schemas/v1/` | **15 JSON Schemas — the vocabulary of the whole system** | adding a field or an enum value |
| `src/research/extraction/` | PDF and Markdown → normalized text, chunks, seven extraction statuses | changing how sources are read |
| `src/research/importers/` | content-addressed import, dedup, page rendering | changing what import accepts |
| `src/research/indexing/`, `search/` | SQLite FTS5 build and query, reproducible `index_hash` | changing retrieval |
| `src/research/runs/` | lifecycle (phase + disposition), work packets, stage promotion, `inspect` | changing the workflow's state machine |
| `src/research/validation/` | **the 25 checks and the publication gate** | changing what blocks a report |
| `src/research/reporting/` | Markdown renderer, overstatement detection, template | changing report output |
| `src/research/profiles/` | `default.yaml`, `medicine.yaml` — per-domain strictness | **the first thing most forks customize** |
| `src/research/ui/` | read-only local web view (`research ui`) | changing how a run is displayed |
| `src/research/security/` | path containment, filename sanitization, atomic writes | almost never — read section 5 first |

### The evidence that the tool works

| Path | What lives here |
|---|---|
| `tests/unit/` | properties provable without a workspace — vocabularies, packaging, profiles, foundations |
| `tests/integration/` | the real thing end to end: import → index → run → validate → report, over a real workspace |
| `tests/benchmark/` | the ten corpus cases, each naming the **specific** gate that must catch it |
| `benchmark/` | `build_corpus.py` (synthesizes nine documents; nothing copyrighted), `expected/`, `compare_hosts.py` |

### What the repository says about itself

| Path | What it is | For a fork |
|---|---|---|
| `README.md` | what this is and how to use it | keep |
| `AGENTS.md` | this file | keep, edit as you change the layout |
| `PROJECT_GOAL.md` | **the specification.** Authoritative, and does not change | keep |
| `GOAL.md` | the *working* goal of the original build — a log of what was found and fixed | **replace with your own, or delete.** It is not about your fork |
| `CHANGELOG.md` | every change, written to name the defect rather than the feature | keep the format; it is why this repo is auditable |
| `docs/architecture.md` | trust boundaries, authority model, determinism, module map | keep |
| `docs/security-model.md` | threat model, and an explicit list of what is **not** protected | keep |
| `docs/validation-rules.md` | the 25 checks, the profile rules, and why `not_evaluated` blocks | keep |
| `docs/release-checklist.md` | gate status, **including the gates that are not met** | keep the honesty; the status is about the original build |
| `docs/lessons-carried-forward.md` | failures from a predecessor project, and where each is now enforced | read before changing any gate |
| `workflow/canonical-workflow.md` | the research loop, shipped into every generated workspace | keep |
| `prompts/` | copy-paste prompts for running research, reviewing, and auditing | keep |

### Inside a workspace (not this repo)

```
research.yaml              configuration; its hash is recorded in every run
originals/sha256/ab/cd/…   imported bytes, content-addressed, never modified
documents/manifests/       one Document artifact per source
documents/normalized/      the single canonical text every locator resolves against
documents/renders/         one PNG per PDF page, hashed
indexes/                   SQLite FTS5 + a reproducible index_hash
runs/<run-id>/
  manifest.json            phase + disposition; the run's state
  events.jsonl             append-only: how it got there
  packets/                 your instructions, one per stage
  responses/               where YOU write — candidates, not yet accepted
  evidence/ claims/ reviews/ relationships/ amendments/ retrieval/
                           canonical artifacts, written only by promotion
  validation/              the verdict, and the roster it was computed over
  report/                  rendered Markdown + manifest
```

---

## 4. The research workflow

Ten stages. Eight are yours; two are the CLI's.

```
planning → retrieval → evidence_extraction → synthesis → contradiction_review
   → citation_review → methodology_review → independent_review → final_validation → report
```

The loop, for every stage in order:

```bash
research status <run-id>                    # where it is, what is blocking it
# read runs/<run-id>/packets/NN-<stage>.json — the packet, not any doc, is your instruction set
# write plain JSON to the responses/ path that packet names
research validate <run-id> --stage <stage>  # accept ONE stage; this is what promotes it
```

Then `research validate <run-id>` for the whole run, and `research report <run-id>`.

Four rules that catch people out:

- **A stage is complete when its artifact validates, never because you wrote a file.** Output in
  `responses/` is a candidate.
- **You do not compute `artifact_hash`.** Write plain JSON; the CLI stamps it. A hash you supply
  that does not match its body is refused, not silently re-stamped.
- **Promotion is all-or-nothing**, and stages cannot be skipped.
- **`unable_to_determine` is a successful outcome.** So is a blocked report.

`workflow/canonical-workflow.md` is the full version, including what each stage owes and the
independence rules. `prompts/` has the prompts to drive it.

---

## 5. Invariants — do not break these

Every one of these exists because it was once broken here. `CHANGELOG.md` names the incident.

1. **`not_evaluated` blocks publication exactly as `failed` does.** "Nobody looked" is not "nothing
   found". Anything that treats an unevaluated check as acceptable is a bug, in any layer —
   including a stylesheet.
2. **Never restate a schema enum.** Ask `research.artifacts.registry.schema_enum(...)`, or derive
   from the `StrEnum`. A hand-copied vocabulary silently drops values added later, and the value it
   drops lands in whichever branch nobody thought about — reliably the reassuring one.
3. **Fail closed on a value you do not recognise.** A status this build has never heard of blocks;
   it does not get a benign default. Values arrive from JSON on disk, so "impossible" is reachable.
4. **Verify hashes on read.** `read_artifact` does. Anything that loads an artifact another way must
   too, and a mismatch is a *load error* that forces `not_evaluated` — never a skipped file.
5. **Imported document text is untrusted data, never instructions.** It may carry prompt injection,
   scripts, hostile filenames and traversal paths. Everything that displays it must escape it and say
   where it came from.
6. **Every write proves containment first** — `safe_join` / `assert_within`, symlinks resolved. There
   is no fallback path: an unsafe path raises rather than being redirected somewhere "safe".
7. **The report has no vocabulary of its own** for how well-supported something is. It emits claim
   text verbatim plus a qualifier from a fixed table.
8. **Do not mark a gate met that is not met.** `docs/release-checklist.md` lists what is unmet and
   why. A checklist that only records successes is a marketing document.
9. **A hash is an integrity check, not a signature.** It detects edits made outside the process. It
   cannot detect a host that writes a false artifact and stamps it correctly. Never write a sentence
   that implies otherwise.

---

## 6. How to verify a change

All four must pass. Run them before claiming anything works.

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests benchmark tools
mypy --strict src/research
python tools/generate_schemas.py --check
```

Then the part most people skip: **prove your test can fail.** Re-introduce the defect, watch the
named test go red, and put it back. A test that passes against both the broken and the fixed code is
not guarding anything — several in this repo's history did not, which is why the discipline is
written down.

One trap, learned the hard way: if your edit preserves the file's **byte length** and lands in the
same second, Python reuses the cached `.pyc` and your mutation silently does nothing. Purge
`__pycache__` on both sides of the experiment.

Adding a validation check? It needs, in this order: the check function, an entry in `CHECKS`, a row
in `docs/validation-rules.md` (a test asserts every emitted check id is documented), and a test that
fails without it.

---

## 7. If you are forking this

The tool is domain-agnostic; the *rules* are where your domain goes.

1. **Start with a profile.** `src/research/profiles/medicine.yaml` is the worked example: higher
   risk, `confirmed_independent` required, `verified` forbidden outright, six human-review triggers.
   Copy it. A profile may only name triggers the validator can actually fire — a key that nothing
   reads is rejected at load time rather than silently ignored, which is the whole point.
2. **Replace `GOAL.md`** with your goal, or delete it. It documents the original build's work.
3. **Keep `docs/release-checklist.md` honest.** Its current contents describe the original build;
   restate them for yours, including whatever you have not done.
4. **The benchmark corpus is synthetic and redistributable.** `python benchmark/build_corpus.py`
   generates it; nothing in it is copyrighted. Add cases for gates you add.
5. **Do not add network access to core processing.** If you need it, it belongs in your agent, on
   the other side of the boundary.

---

## 8. When you are unsure

Prefer the answer that refuses. This codebase would rather block a good report than publish a bad
one, and every defect in its history has been the same shape: something reporting "no problem" about
a question it never asked.
