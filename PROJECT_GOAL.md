# Automated AI Research Platform — MVP Implementation Goal

> This document is the **authoritative specification**. Where any other document in this repository
> disagrees with it, this one wins. Implementation status is tracked in `README.md`; a rule being
> unimplemented never makes it non-normative.

## 1. Project Mission

Build an open-source, local-first automated research platform that helps researchers, students, and
developers investigate questions across collections of locally stored documents.

The project must be published as a GitHub repository that users can clone and operate from:

- A local terminal
- A conventional IDE
- Codex
- Claude Code
- Other coding-agent environments capable of reading and writing repository files

The platform must use an evidence-first research workflow. It must help host AI agents discover
relevant information, extract claims and evidence, identify contradictions, review methodology,
validate citations, and produce reproducible research reports.

The platform itself must not embed or launch commercial model APIs, local model servers, Ollama, or a
bundled agent framework. Codex, Claude Code, or another host environment performs the reasoning and
agent delegation. The repository provides deterministic document processing, data contracts, work
packets, validation rules, state management, search, citation resolution, and report generation.

The system must not treat generated text as verified research merely because it sounds plausible or
because multiple agents repeated it. Important conclusions must be linked to immutable evidence,
independently reviewed, uncertainty-labelled, and reproducible.

## 2. Target Users

- Researchers working with collections of papers and reports
- University students conducting literature reviews
- Developers investigating technical questions
- Engineering teams evaluating theories, methods, or design decisions
- Users operating Codex or Claude Code over a local repository

The platform should remain general enough to support multiple research domains while allowing
domain-specific rules through configurable research profiles.

## 3. Core Design Principles

### 3.1 Evidence before synthesis
Agents must collect and structure evidence before producing conclusions. A claim cannot appear in a
publishable report unless it references one or more valid evidence records.

### 3.2 Originals remain authoritative
Original imported files are the ultimate source evidence. The platform must preserve original PDF and
Markdown files without modifying them.

### 3.3 JSON is canonical
Versioned JSON artifacts are the canonical representation of documents, chunks, evidence, claims,
research plans, reviews, run state, validation results, and human amendments. Markdown files are
human-readable renderings of validated JSON artifacts. Markdown output must not silently become more
authoritative than its underlying JSON.

### 3.4 Immutable historical records
Previously completed research artifacts must not be silently overwritten. Corrections, human edits,
schema migrations, and revised interpretations must produce new artifact versions, explicit amendment
records, superseding relationships, and updated artifact hashes.

### 3.5 Local-first operation
The MVP must run locally. The platform must not require an external hosted service to import
documents, extract text, build indexes, search documents, validate artifacts, or generate reports.

### 3.6 Provider independence
The repository must not depend on one AI provider. Agent instructions and work packets must be usable
from both Codex and Claude Code.

### 3.7 Reproducible processing
The platform must record enough information to reproduce deterministic processing steps: source
hashes, configuration versions, workflow versions, extraction tool versions, index settings, search
queries, ranking settings, artifact hashes, and validation results.

Reproducibility does not require identical agent prose across reruns. It requires replayable inputs,
configurations, queries, and validated artifacts.

### 3.8 Explicit uncertainty
The platform must distinguish among directly verified facts, strongly supported conclusions, moderate
or weak support, conflicting evidence, unsupported claims, insufficient evidence, and pending human
review.

### 3.9 Imported content is untrusted
Documents may contain prompt injection, scripts, instructions, malicious links, malformed metadata, or
unsafe filenames. Imported content must never be treated as trusted system instructions.

## 4. MVP Scope

1. Initialize a research workspace.
2. Import local PDF and Markdown files.
3. Preserve and hash original files.
4. Extract normalized document content.
5. Generate page-aware document artifacts.
6. Render every PDF page for visual verification.
7. Detect low-text or image-only pages.
8. Flag pages requiring OCR.
9. Build a reproducible SQLite full-text index.
10. Search indexed content with metadata filtering.
11. Initialize a research run.
12. Generate structured work packets for host agents.
13. Collect research plans, evidence, claims, contradictions, and reviews.
14. Validate schemas, references, citations, hashes, workflow state, and reviewer completeness.
15. Determine whether a report is eligible for publication.
16. Generate a cited Markdown report from validated JSON artifacts.
17. Preserve a complete research audit trail.

## 5. Explicit Non-Goals for Version 1

Do not implement: autonomous web browsing; automatic downloading of source URLs; web search
integrations; embedded commercial model APIs; local model hosting; Ollama integration; distributed
agent execution; knowledge graphs; vector databases; semantic embedding retrieval; continuous
monitoring; scheduled research jobs; automatic OCR; graphical desktop interfaces; web dashboards;
multi-user authentication; cloud storage; automatic execution of links or scripts inside documents.

The architecture should permit future extensions, but these features must not expand the MVP scope.

## 6. Technical Constraints

- Python 3.12
- Apache-2.0 license
- Installable Python package
- CLI command name: `research`
- SQLite with FTS5 for retrieval
- JSON Schema for artifact validation
- Markdown for human-readable output
- SHA-256 for content hashing
- File-based research artifacts
- Deterministic sorting and tie-breaking
- Cross-platform path handling where practical
- Linux and macOS as primary development targets; Windows support where dependencies permit

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
research --help
```

## 7. Public CLI

```text
research init
research import
research index
research search
research run
research status
research inspect
research validate
research report
```

All commands must support `--help` and `--json` when machine-readable output is applicable. Commands
must return stable machine-readable result structures.

## 8. Command Contracts

### 8.1 `research init`
Create a new research workspace: create the directory, default configuration, standard directory
structure, default research profiles, workflow version metadata, schema references, thin `AGENTS.md`
and `CLAUDE.md` entry files, and the canonical shared workflow instructions. Refuse to overwrite an
existing non-empty workspace unless explicitly allowed.

Output: workspace path, configuration path, workflow version, schema version, initialization status.

### 8.2 `research import`
Validate input paths. Reject unsafe paths. Preserve original bytes. Calculate SHA-256 hashes. Detect
exact duplicates. Assign stable document identifiers. Extract normalized content. Extract metadata
when available. Preserve page boundaries. Attempt table and figure-region detection. Render every PDF
page. Mark low-text or image-only pages as `ocr_required`. Create document manifests. Record
extraction warnings and failures. Never execute document instructions, links, scripts, or embedded
commands. Never automatically fetch URLs found in Markdown.

Importing the same bytes again must not create a new logical document. Different files with identical
hashes must resolve to the same document identity while preserving import aliases in provenance
metadata. The import process must not claim successful extraction merely because a source file was
copied successfully.

Allowed extraction statuses:

```text
extracted
partially_extracted
ambiguous
unsupported_format
ocr_required
processing_failed
human_review_required
```

Output: imported count, duplicate count, warning count, failed count, document IDs, manifest paths,
exit status.

### 8.3 `research index`
Read canonical document and chunk artifacts. Validate documents before indexing. Build SQLite FTS5
tables. Store searchable metadata. Record tokenizer and ranking configuration. Record SQLite version.
Produce deterministic tie-breaking. Store index manifest and hash. Support complete rebuilding from
canonical artifacts. Never treat the index as authoritative evidence.

Deterministic result order:

```text
rank DESC,
document_id ASC,
page_number ASC,
chunk_id ASC
```

Index reproducibility requires recording: SQLite version, tokenizer, tokenizer configuration, ranking
function, input artifact hashes, input ordering, database schema version, chunking configuration, and
extraction version.

### 8.4 `research search`
Search indexed chunks. Support metadata filters. Return ranked results, stable chunk IDs, document
IDs, exact citation locators, page and section information, and snippets without altering source
meaning. Distinguish FTS ranking from evidence quality. Never label a search result as verified
evidence automatically.

Machine-readable results must include: query, query normalization, applied filters, ranking
configuration, result rank, document ID, document version ID, chunk ID, page, section path, text span,
locator, and source metadata.

### 8.5 `research run`
Create a unique run ID. Store the research question. Select a research profile. Initialize lifecycle
state. Record source collection state. Record workflow and schema versions. Generate stage work
packets. Create directories for responses and artifacts. Record host-agent information when available.
Never store hidden chain-of-thought. Never claim that an agent stage has completed before validated
output exists.

The command initializes the run but does not perform model reasoning itself.

### 8.6 `research status`
Show: current lifecycle state, completed stages, pending stages, failed validation gates, missing
artifacts, human-review requirements, independent-review status, report eligibility, superseded
artifacts, and unresolved contradictions.

### 8.7 `research inspect`
Support document, chunk, evidence, claim, and review inspection; citation resolution; page-render
lookup; visual-region lookup; human-readable and JSON output. For evidence inspection, show enough
context to verify whether the cited passage genuinely supports the associated claim.

### 8.8 `research validate`
Validate all JSON artifacts against versioned schemas. Verify source hashes, artifact hashes, document
references, and evidence references. Resolve text locators and visual locators. Detect dangling
references. Verify claim-evidence links, review completeness, lifecycle transitions, required
contradiction review, citation review, and independent review. Evaluate human-review triggers. Produce
a validation result artifact. Determine whether the report may be published.

Validation must fail report eligibility when: a claim lacks evidence; an evidence locator cannot be
resolved; a source hash does not match; a required review is missing; reviewer independence is
insufficient; OCR-required material is used as evidence without human review; a visual interpretation
is uncertain; a citation is related but does not support the claim; a required contradiction remains
undisclosed; an artifact does not conform to its schema; or a lifecycle transition is invalid.

### 8.9 `research report`
Require a successful validation result. Refuse publication when report gating fails. Render claims and
conclusions from canonical JSON. Include citations, contradictory evidence, uncertainty, limitations,
human-review status, unresolved questions, and provenance information. Generate a report manifest.
Hash the generated report. Never silently repair invalid research artifacts.

A report may be generated in a clearly marked draft mode before full validation, but it must not be
labelled published or validated.

## 9. Repository and Workspace Structure

See `docs/architecture.md`. The generated workspace uses:

```text
workspace/
├── research.yaml
├── originals/sha256/
├── documents/{manifests,normalized,pages,renders,tables,figures}/
├── indexes/{research.sqlite3,index-manifest.json}
├── imports/import-events.jsonl
├── runs/<run-id>/{manifest.json,plan.json,packets,responses,evidence,claims,reviews,validation,amendments,report}/
├── profiles/
├── logs/
└── cache/
```

## 10. Canonical Research Workflow

```text
planning
→ retrieval
→ evidence_extraction
→ synthesis
→ contradiction_review
→ citation_review
→ methodology_review
→ independent_review
→ final_validation
→ report
```

The workflow must be stored once as a canonical repository document. `AGENTS.md` and `CLAUDE.md` must
be thin entry files that point to the same workflow and contracts. Do not maintain separate research
logic for Codex and Claude Code. Both host environments must use the same schemas, stage order,
work-packet format, report gates, and benchmark, and produce artifacts with the same validation
requirements. Host agents may delegate stages to fresh subagents where supported.

## 11. Run Lifecycle

Primary states:

```text
initialized, planned, retrieved, evidence_extracted, synthesized,
contradiction_reviewed, citation_reviewed, methodology_reviewed,
independently_reviewed, validation_passed, report_eligible, published
```

Additional states:

```text
blocked, review_pending, human_review_required, validation_failed, superseded, cancelled
```

The CLI must enforce valid transitions. Invalid examples: `initialized` → `published`; `retrieved` →
`independently_reviewed`; `validation_failed` → `published`; `human_review_required` →
`report_eligible` without a valid human amendment or review.

Lifecycle changes must be recorded as append-only events containing previous state, new state,
timestamp, triggering command or artifact, validation result, actor type, artifact hashes, and reason.

## 12. Stage Contracts

Every work packet must define: stage name, run ID, research question, allowed inputs, required
outputs, relevant schemas, required evidence, prohibited context, completion criteria, validation
command, failure conditions, and human-review triggers.

**Planning** → `ResearchPlan`: main question, subquestions, definitions, scope, inclusion/exclusion
criteria, search terms, evidence requirements, validation criteria, expected limitations, high-risk
classifications, conditions for insufficient evidence.

**Retrieval** → search queries, ranked chunk references, retrieval log, coverage notes. Must not
create final claims.

**Evidence extraction** → `Evidence` records identifying exact supporting text, relevant context,
evidence type, source quality indicators, method details, assumptions, limitations, possible
contradictions, and visual evidence requirements. Must not silently infer unreadable visual content.

**Synthesis** → draft `Claim` records, claim-evidence relationships, preliminary conclusions, explicit
assumptions. Must distinguish direct fact, inference, interpretation, hypothesis, correlation, causal
conclusion, opinion, and insufficient evidence.

**Contradiction review** → contradictory evidence, alternative explanations, unresolved conflicts,
coverage gaps. The reviewer must actively search for disagreement rather than only checking already
selected sources.

**Citation review** → determine whether the source exists, the locator resolves, the cited passage is
accurate, the passage supports the claim, the paraphrase preserves meaning, the citation is merely
related but non-supporting, context changes interpretation, and whether a visual citation needs human
verification.

**Methodology review** → study design, sample size, data quality, controls, assumptions, statistical
methods, reproducibility, conflicts of interest, generalizability, measurement limitations, dataset
reuse, publication status. The platform must not assume a source is methodologically strong merely
because it is published.

**Independent review** → support assessment, citation assessment, contradiction assessment,
reviewer-independence declaration, human-review recommendation. Excluded context: primary synthesis
rationale, primary confidence classification, previous reviewer conclusions, suggested final wording,
hidden reasoning, persuasive summaries produced by the primary agent.

**Final validation** → `ValidationResult`, report eligibility decision, human-review requirements,
blocking errors, warnings.

**Report** → Markdown report, report manifest, report hash, citation index.

## 13. Agent Independence Contract

The independent reviewer must not receive the primary agent's reasoning or confidence judgment.

```json
{
  "review_independence": {
    "primary_rationale_excluded": true,
    "primary_confidence_excluded": true,
    "prior_review_conclusions_excluded": true,
    "fresh_agent_context_requested": true,
    "host_confirmed_fresh_context": false,
    "status": "procedurally_isolated"
  }
}
```

Allowed statuses: `confirmed_independent`, `procedurally_isolated`, `not_confirmed`,
`not_independent`.

A run must remain `review_pending` when independence does not satisfy the active research profile.
High-risk profiles may require `confirmed_independent`. The default profile may permit
`procedurally_isolated` but must disclose that status in the report.

## 14. Canonical Artifact Schemas

Version JSON schemas for at least: `Document`, `DocumentVersion`, `Chunk`, `Evidence`, `Claim`,
`Review`, `ResearchPlan`, `RunManifest`, `ValidationResult`, `Amendment`, `IndexManifest`,
`ReportManifest`.

Every artifact must include:

```json
{
  "schema_name": "Evidence",
  "schema_version": "1.0.0",
  "artifact_id": "EVD-...",
  "artifact_hash": "sha256:...",
  "created_at": "RFC3339 timestamp",
  "created_by": {
    "actor_type": "host_agent",
    "host": "codex",
    "model_identifier": "recorded when available"
  }
}
```

Do not record hidden chain-of-thought. Agent rationale fields must contain concise, reviewable
conclusions or justifications, not private reasoning traces.

## 15. Identifier Rules

- **Source document ID** = `SHA-256(original_file_bytes)`. Must not depend on filename, import path,
  import time, user name, or workspace location.
- **Document version ID** derives from source document hash, extraction configuration hash, extraction
  toolchain version, and normalization version.
- **Chunk ID** derives from document version ID, page, section path, character span, and chunking
  configuration.
- **Evidence ID** derives from document version ID, locator, exact evidence content, and extraction
  type.
- **Claim ID** uses a stable generated identifier such as UUIDv7. A claim's wording may change through
  superseding versions.
- **Run ID** is unique and independent of the current timestamp, though a timestamp may be stored as
  metadata.

The displayed identifier may use a prefix and shortened representation, but the complete hash must be
retained.

## 16. Document Model

A `Document` represents immutable original bytes. A `DocumentVersion` represents a specific normalized
extraction of that document.

Required: document ID, source hash, original filename aliases, media type, file size, import events,
title, authors, organization, publication date, source URL metadata, retrieval date, language, page
count, extraction status, extraction toolchain, extraction warnings, OCR-required pages, render
manifest, related-document relationships.

Original files must be stored content-addressably: `originals/sha256/ab/cd/<full-sha256>`.

## 17. PDF Processing Requirements

Preserve original bytes; calculate a source hash; determine page count; extract page-aware text;
preserve page boundaries; extract document metadata; attempt heading and section detection; attempt
table extraction; attempt figure-region and caption detection; render every page; hash every page
render; record render dimensions; detect low-text pages; mark image-only or unreadable pages as
`ocr_required`; record all extraction warnings; never silently infer inaccessible content.

Table and figure extraction is fallible. Use statuses: `extracted`, `partially_extracted`,
`not_detected`, `ambiguous`, `unsupported`, `ocr_required`, `human_review_required`. The system must
not state that all tables or figures were successfully extracted unless validation confirms it.

### 17.1 Page rendering
Rendering every page is required for visual provenance. Use a fixed, recorded rendering configuration
and record renderer name, renderer version, resolution/DPI, output dimensions, output format, and
render hash. For cited visual regions, retain a stable region locator and optionally a
higher-resolution crop.

## 18. Markdown Processing Requirements

Preserve original bytes; calculate a source hash; parse headings and sections; preserve code blocks
and tables; preserve link destinations as metadata; do not follow links; do not execute HTML, scripts,
or embedded instructions; record source line ranges; generate stable text locators; escape unsafe HTML
in generated reports by default.

## 19. Chunk Model

Chunks are retrieval units, not authoritative evidence by themselves. A chunk must include: chunk ID,
document version ID, page number or source line range, section path, start offset, end offset, exact
normalized text, text hash, context boundaries, chunking configuration version, overlap metadata,
index eligibility, and extraction warnings. Chunk boundaries must not destroy the ability to resolve
evidence back to the original source.

## 20. Evidence Model

Evidence types: `direct_statement`, `definition`, `experimental_result`, `statistical_result`,
`method_description`, `limitation`, `table_value`, `figure_observation`, `metadata_fact`,
`citation_relationship`, `expert_opinion`, `derived_calculation`.

```json
{
  "evidence_id": "EVD-...",
  "document_id": "sha256:...",
  "document_version_id": "DVER-...",
  "evidence_type": "experimental_result",
  "locator": {
    "type": "text_span",
    "page": 14,
    "section_path": ["4 Results", "4.2 Evaluation"],
    "chunk_id": "CHK-...",
    "start_offset": 412,
    "end_offset": 683,
    "span_sha256": "sha256:..."
  },
  "exact_text": "Exact extracted passage",
  "context_before": "Relevant preceding context",
  "context_after": "Relevant following context",
  "extraction_method": "page_text_extraction",
  "extraction_status": "extracted",
  "human_review_required": false
}
```

Evidence records must preserve exact quoted text internally. Reports may paraphrase evidence, but
citation review must compare the paraphrase against the exact source text.

## 21. Visual Locator Contract

Normalized coordinate system: `x, y, width, height ∈ [0, 1]`, origin top-left.

```json
{
  "locator": {
    "type": "visual_region",
    "page": 12,
    "render_sha256": "sha256:...",
    "coordinate_system": "normalized_top_left_0_to_1",
    "bounding_box": { "x": 0.14, "y": 0.28, "width": 0.63, "height": 0.41 },
    "render_width": 1600,
    "render_height": 2200
  },
  "region_type": "figure",
  "caption": "Figure 3. Comparison of methods",
  "interpretation_status": "human_review_required"
}
```

Vector charts must be verified through page-level visual evidence. The MVP must not silently infer
chart values that cannot be resolved reliably.

## 22. Claim Model

Claim types: `direct_fact`, `definition`, `descriptive_result`, `comparative_result`,
`methodological_claim`, `causal_claim`, `correlational_claim`, `interpretation`, `hypothesis`,
`recommendation`, `insufficient_evidence_finding`.

Claim lifecycle statuses: `draft`, `evidence_linked`, `citation_checked`, `methodology_reviewed`,
`independently_reviewed`, `accepted`, `rejected`, `superseded`.

Support classifications: `verified`, `strongly_supported`, `moderately_supported`,
`weakly_supported`, `conflicting_evidence`, `unsupported`, `unable_to_determine`.

A support classification must not substitute for lifecycle status.

## 23. Confidence Rules

Do not expose an aggregate numeric confidence score in the MVP. Confidence must be categorical and
supported by explicit factor ratings: evidence directness, source quality, source independence,
methodology quality, contradictory evidence, evidence coverage, citation validity, reviewer agreement,
reviewer independence, visual certainty, OCR dependency. Ratings: `high`, `medium`, `low`, `unknown`,
`not_applicable`.

### 23.1 `verified`
Reserved for directly checkable facts that are supported by exact evidence, have valid locators, pass
citation review, pass independent review, have no material unresolved contradiction, do not depend on
uncertain visual interpretation or unreviewed OCR output, and are within the source's direct scope.
Broader theoretical, causal, or generalizable conclusions cannot be labelled `verified`.

### 23.2 `strongly_supported`
Only when multiple relevant evidence records support the claim, important citations pass review,
source quality is adequate, source independence is assessed, contradictions are absent/resolved/
disclosed, methodological limitations do not overturn the conclusion, and independent review agrees.
Broader conclusions can be at most `strongly_supported`.

### 23.3 Other classifications
`moderately_supported` when evidence is meaningful but incomplete; `weakly_supported` when limited or
indirect; `conflicting_evidence` when substantial evidence disagrees; `unsupported` when evidence does
not support the claim; `unable_to_determine` when evidence is insufficient.

## 24. Source Independence

Multiple documents must not automatically count as multiple independent sources. Track relationships:
`duplicate`, `republication`, `revision_of`, `translation_of`, `summarizes`, `cites`, `derived_from`,
`shares_primary_dataset`, `shares_experimental_result`, `unknown`.

A `SourceRelationship` includes source document, related document, relationship type, evidence for the
relationship, confidence, and human-review status. The platform must identify identical files under
different names, preprint/published versions, reports copied from a primary study, multiple articles
relying on the same dataset, translations, and revised editions.

## 25. Review Model

Review types: `citation_review`, `methodology_review`, `contradiction_review`, `independent_review`,
`human_review`.

Every review includes review ID, review type, reviewed artifact IDs, reviewer identity metadata,
reviewer-independence status, decision, findings, blocking issues, non-blocking warnings, required
amendments, timestamp, and artifact hash.

Decisions: `passed`, `passed_with_warnings`, `failed`, `incomplete`, `human_review_required`.

## 26. Human Review Triggers

Mandatory when: an unresolved contradiction affects a material conclusion; a citation fails or only
partially supports a claim; a visual interpretation is uncertain; evidence depends on an OCR-required
page; methodology quality is low or unknown for an important claim; reviewer independence is missing; a
profile marks the topic high-risk; a source is malformed or only partially extracted; a claim depends
on an ambiguous table or chart; a causal claim is inferred from correlational evidence; source
independence cannot be established; a report would otherwise overstate available evidence; or a
required artifact was manually repaired outside the amendment process.

Human actions must produce explicit amendment or review artifacts. Do not modify historical records
silently.

## 27. Research Profiles

Profiles: `default`, `computer_science`, `engineering`, `medicine`, `finance`, `social_science`.

A profile may configure preferred source types, required source metadata, evidence-quality rules,
methodology-review criteria, risk classification, human-review triggers, reviewer-independence
requirements, report sections, prohibited confidence classifications, required contradiction coverage,
source-recency rules, and publication-status handling.

The shared workflow must remain consistent across profiles. Profiles customize validation rules, not
the fundamental artifact model.

## 28. Work Packet Format

```json
{
  "packet_id": "PKT-...",
  "run_id": "RUN-...",
  "stage": "independent_review",
  "workflow_version": "1.0.0",
  "schema_versions": { "Claim": "1.0.0", "Evidence": "1.0.0", "Review": "1.0.0" },
  "allowed_inputs": ["question", "claims", "evidence", "contradictions", "source_metadata"],
  "excluded_inputs": ["primary_rationale", "primary_confidence", "previous_review_conclusions"],
  "required_outputs": ["reviews/independent-review.json"],
  "completion_criteria": [
    "all material claims reviewed",
    "citation support assessed",
    "contradictions assessed",
    "independence declaration recorded"
  ],
  "validation_command": "research validate RUN-... --stage independent_review"
}
```

Agent-produced output must not be accepted solely because the file exists. It must pass schema and
semantic validation.

## 29. Provenance Requirements

Every run must record: research question, research profile, source document hashes, document version
hashes, search queries, search filters, search result IDs, retrieval order, workflow version,
configuration hash, schema versions, host environment, model identifier when available, tool versions,
timestamps, agent stage artifacts, human edits, amendments, artifact hashes, validation results, and
report hash.

Never record hidden chain-of-thought. Record only structured outputs, concise justifications,
decisions, citations, validation evidence, and tool/host metadata.

## 30. Schema Versioning and Migration

Every artifact must declare its schema name and version. Unsupported schema versions must fail
clearly. Migrations must be explicit and must create new artifacts. Historical source artifacts must
not be overwritten. Migration records must include source and destination hashes. A migrated artifact
must reference the artifact it supersedes. Reports must record which schema versions were used.

## 31. Amendments and Human Edits

An `Amendment` includes amendment ID, target artifact ID, target artifact hash, amendment type,
changed fields, reason, human identity metadata, timestamp, replacement artifact ID, replacement
artifact hash, and review requirement.

Types: `metadata_correction`, `locator_correction`, `claim_rewording`, `evidence_reclassification`,
`human_visual_verification`, `human_ocr_verification`, `review_override`, `withdrawal`.

Any amendment affecting a published report must trigger revalidation.

## 32. Report Requirements

A validated report contains: title, research question, scope, research method, source summary, main
findings, claims with support classifications, supporting evidence, contradictory evidence,
methodological limitations, unresolved questions, human-review status, reviewer-independence status,
insufficient-evidence findings, references, provenance summary, and validation summary.

Each material claim must cite evidence IDs. Citations must resolve to document, page or source lines,
section, and exact text span or visual region.

The report must disclose conflicts, weak evidence, missing evidence, OCR requirements, uncertain
visuals, pending reviews, and reviewer-independence limitations.

**The report generator must not strengthen the language of a claim beyond its validated
classification.**

## 33. Security Model

Imported files and agent outputs are untrusted. Never execute imported document instructions,
embedded scripts, or shell commands found in documents. Never fetch links automatically. Never allow
imported text to alter workflow configuration, redefine agent roles, or choose tools. Validate every
output path before writing. Restrict writes to the workspace root. Reject path traversal, unsafe
archive entries, and unsafe symbolic links. Sanitize imported filenames, preserving original names
only as metadata. Escape unsafe HTML in generated Markdown. Redact secrets from logs. Never serialize
environment variables into artifacts. Keep API keys outside the workspace. Do not place credentials in
work packets. Treat malformed parsers and PDFs as potential security risks. Apply file-size and
resource limits. Network access is disabled by default.

Agent packets must clearly separate `TRUSTED WORKFLOW INSTRUCTIONS` from `UNTRUSTED DOCUMENT CONTENT`.

## 34. Error Handling

Commands must provide human-readable error messages, machine-readable errors under `--json`, stable
error categories, appropriate exit codes, and partial-success reporting where applicable.

```text
0 = success
1 = general failure
2 = invalid arguments
3 = schema validation failure
4 = source processing failure
5 = report gating failure
6 = human review required
7 = unsafe path or security rejection
8 = unsupported artifact or schema version
```

A human-review requirement is an expected workflow state, but automation still needs a
machine-readable exit status. **Do not present partial processing as complete success.**

## 35. Logging

Logs must be structured where practical, timestamped, free of secrets, separated from canonical
artifacts, configurable by verbosity, and suitable for debugging deterministic processing. Logs are
not authoritative research evidence.

## 36. Testing Requirements

**Unit:** SHA-256 hashing, stable identifiers, duplicate imports, path safety, symlink handling,
metadata normalization, page anchors, text locators, visual locators, bounding-box validation, schema
validation, schema version rejection, FTS ranking, deterministic tie-breaking, confidence rules, claim
lifecycle rules, run lifecycle rules, source-independence relationships, report gating, amendment
behavior, secret redaction.

**Integration:** text-based PDF, multi-column PDF, Markdown file, Markdown table, PDF table, raster
figure, vector figure, figure caption, malformed PDF, encrypted/unsupported PDF, image-only page,
low-text page, duplicate document, revised document, conflicting sources, related but non-supporting
citation, prompt-injection text, unsafe filename, path traversal, partial extraction, human-review
workflow, failed independent review, published report revalidation after amendment.

**Benchmark:** known source passages, known page citations, known visual-region citations, supported
claims, unsupported claims, deliberate contradictions, related but non-supporting citations, duplicate
sources, dependent sources, a source with weak methodology, an image-only page, prompt-injection
content, and an insufficient-evidence question. Must not depend on copyrighted documents that cannot
be redistributed.

## 37. Codex and Claude Code Acceptance

Both must complete the same benchmark using the same repository, workflow, schemas, work packets, CLI,
and report gates. Expected prose may differ; required artifacts, references, validation behavior, and
benchmark outcomes must remain equivalent. Do not create separate simplified rules for one host.

## 38. MVP Release Gates

**38.1 Import determinism** — re-importing identical bytes produces the same document ID; duplicates
do not create duplicate logical documents; import aliases remain traceable.

**38.2 Extraction integrity** — page-aware text preserved where available; every PDF page has a
render; every render has a stable hash; low-text/image-only pages flagged; OCR-required pages never
silently treated as reliable text evidence.

**38.3 Index determinism** — rebuilding from identical artifacts produces equivalent searchable
contents; tie-breaking deterministic; configuration recorded.

**38.4 Citation resolution** — every citation resolves to a source; text citations resolve to the
correct page and span; visual citations resolve to the correct render and region; dangling references
block publication.

**38.5 Claim support** — every report claim references evidence; related but non-supporting citations
rejected; unsupported claims cannot be `verified` or `strongly_supported`; broader conclusions cannot
be `verified`.

**38.6 Contradiction detection** — seeded contradictions surfaced, attached to relevant claims,
unresolved material contradictions disclosed, required contradictions trigger human review.

**38.7 Independent review** — reviewer packet excludes prohibited primary context; independence status
recorded; missing independence blocks or qualifies publication per profile.

**38.8 Artifact validation** — all artifacts validate without manual schema repair; hashes resolve;
invalid lifecycle transitions rejected; unsupported schema versions fail clearly.

**38.9 Report gating** — invalid citations block publication; missing reviews block publication;
human-review requirements disclosed; reports disclose conflicts and uncertainty; report language does
not exceed validated support classifications.

**38.10 Cross-host benchmark** — Codex and Claude Code both complete the benchmark producing
schema-valid, report-eligible outputs under the same contracts.

## 39. Definition of Done

```bash
git clone <repository>
cd <repository>
python -m venv .venv
source .venv/bin/activate
pip install -e .
research init example-workspace
cd example-workspace
research import ./sources
research index
research search "research question"
research run --question "research question" --profile default
```

The user can then use Codex or Claude Code to execute the generated work packets and produce a
research plan, retrieval records, evidence records, claims, contradiction reviews, citation reviews,
methodology reviews, independent reviews, and a validation result. Then:

```bash
research validate <run-id>
research report <run-id>
```

and receive either a validated, cited Markdown report, or a precise explanation of why publication is
blocked.

**The platform must prefer refusing report eligibility over publishing an unsupported or incorrectly
cited conclusion.**

## 40. Implementation Order

1. **Foundation** — package structure, CLI framework, workspace init, configuration, error model,
   hashing, stable identifiers, JSON Schema loading, artifact read/write utilities, path safety.
2. **Document import** — content-addressed original storage, PDF importer, Markdown importer, document
   manifests, duplicate handling, extraction statuses, page rendering, OCR-required detection.
3. **Normalization and chunking** — page-aware normalized Markdown, section extraction, chunk
   generation, stable text locators, visual-region model, extraction warnings.
4. **Indexing and search** — SQLite schema, FTS5 index, metadata filters, deterministic ranking,
   search JSON output, citation-locator output.
5. **Run management** — run manifests, lifecycle transitions, stage packets, status, inspect,
   append-only run events.
6. **Research artifacts** — ResearchPlan, Evidence, Claim, Review, ValidationResult, Amendment schemas.
7. **Validation** — schema, hash, reference validation; locator resolution; claim-evidence validation;
   review completeness; reviewer-independence checks; human-review triggers; report gating.
8. **Reporting** — deterministic Markdown rendering, citation index, conflict disclosure, uncertainty
   disclosure, provenance summary, report manifest and hash.
9. **Benchmark** — redistributable fixtures, known claims and citations, contradiction cases,
   unsupported cases, OCR-required case, prompt-injection case, Codex and Claude Code workflows.
10. **Release preparation** — documentation, security review, test coverage, cross-platform checks,
    Apache-2.0 license, contributing guide, example workspace, release checklist.

## 41. Coding Standards

Type hints throughout public interfaces; small modules with clear responsibilities; dataclasses or
validated models for internal structures; explicit exceptions; dependency injection where it improves
testing; deterministic serialization; UTF-8; atomic file writes (temporary file followed by rename);
clear separation between canonical artifacts and caches; no hidden global mutable state; no network
access in core processing; no provider-specific agent code.

All canonical JSON must use stable serialization when hashes depend on serialized content. Tests must
not depend on timing-sensitive ordering.

## 42. Documentation Requirements

The README must explain what the project does and does not do, how host agents participate, why
originals are preserved, why JSON is canonical, how Markdown reports are generated, how to initialize
a workspace, how to import and index documents, how to create a run, how to use Codex and Claude Code,
how to validate a run, why a report may be blocked, how human review works, security limitations, and
current MVP limitations.

Architecture documentation must explain trust boundaries, artifact authority, run lifecycle, agent
stage isolation, source independence, citation resolution, schema migration, and determinism
boundaries.

## 43. Final Authority Model

1. Original source files are the authoritative evidence.
2. Content hashes establish the identity of original source files.
3. Versioned JSON artifacts are the canonical representation of processing, claims, evidence, reviews,
   and run state.
4. Valid locators connect evidence records to original source files.
5. Validation results determine whether research artifacts are internally consistent and
   report-eligible.
6. Markdown reports are human-readable renderings of validated JSON artifacts.
7. Human corrections must be represented through explicit review or amendment artifacts.
8. **No agent-generated prose is authoritative merely because it was generated confidently.**

## 44. Core Product Rule

The system must never present an important statement as validated research unless: the statement is
represented as a claim; the claim references valid evidence IDs; the evidence resolves to immutable
source material; the citation genuinely supports the claim; relevant contradictions were considered;
required methodology review was completed; independent review was completed at the required level;
human-review conditions were resolved or clearly disclosed; and the report passed all applicable
validation gates.

When the evidence is insufficient, the correct output is:

```text
unable_to_determine
```

The platform must treat this as a **successful research outcome, not a system failure**.
