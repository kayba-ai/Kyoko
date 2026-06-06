# 0013 - Event Envelope Contract

Status: implemented for v0 ingest (documents existing behavior; answers Q20)
Date: 2026-06-03
Blocks: Q20

Schema: [`../schemas/event-envelope.schema.json`](../schemas/event-envelope.schema.json)
Helper: [`../../kyoko/event_envelope.py`](../../kyoko/event_envelope.py)
Tests: [`../../tests/test_event_envelope.py`](../../tests/test_event_envelope.py)

## Purpose

This is the single written contract for the **normalized ingest event envelope**:
the one JSON shape every Kyoko ingest path produces before it touches SQLite.
[`0001-canonical-model.md`](0001-canonical-model.md) defines the entities; this spec
defines the **wire shape** that carries them into the store and pins down what is
required, what is optional, and how OTLP and the SDK both map onto it.

Before this spec, normalization was ad-hoc across [`../../kyoko/otlp.py`](../../kyoko/otlp.py),
[`../../kyoko/sdk.py`](../../kyoko/sdk.py), and [`../../kyoko/span_normalize.py`](../../kyoko/span_normalize.py)
with no envelope written down. This documents the shape they already converge on. It
does not change ingest behavior.

OTLP and framework-native schemas are **input formats**, not the envelope. They are
normalized *into* the envelope first (`0001` §"OTLP and framework-native schemas are
input formats").

## Where the envelope is accepted

| Path | Producer | Envelope role |
|---|---|---|
| `kyoko ingest <path>` / `POST /api/ingest` | any adapter, hand-authored fixtures | the envelope, ingested directly |
| `kyoko ingest-otlp` / `POST /api/ingest-otlp` / `POST /v1/traces` | `kyoko.otlp.normalize_otlp_json` | OTLP/GenAI JSON normalized into the envelope, then ingested |
| SDK recorder flush | `kyoko.sdk.KyokoRecorder` | emits the same envelope shape |
| offline importers | `kyoko.hermes_import`, `kyoko.openclaw_import` | emit the envelope shape |

The reference implementation of the consumer is
`kyoko.storage.ingest_source_payload`.

## Top-level shape

A single JSON object:

```jsonc
{
  "fixture_version": "kyoko.source_events.v1",   // optional, advisory only
  "name": "...",                                  // optional, free label
  "description": "...",                            // optional
  "profile": { ... },                              // REQUIRED, single object
  "sources": [ ... ],
  "agent_identities": [ ... ],
  "workflow_nodes": [ ... ],
  "queues": [ ... ],
  "tasks": [ ... ],
  "task_attempts": [ ... ],
  "runs": [ ... ],
  "spans": [ ... ],
  "handoffs": [ ... ],
  "timeline_events": [ ... ]
}
```

Rules:

- `profile` is the **only** required top-level member. It is one object, never a list
  — one envelope carries exactly one profile (`0001` §"One Profile is the product
  boundary"; SCOPE: single workflow).
- Every collection is optional. A missing collection is treated as `[]`. If present it
  **must** be an array of objects.
- `fixture_version` is advisory: ingest never reads it. Two spellings exist in the
  wild and both validate — `kyoko.source_events.v1` (OTLP normalizer + importers) and
  `kyoko.source_fixture.v1` (the original hand-authored Hermes fixture). New producers
  should emit `kyoko.source_events.v1`.
- `name` / `description` are free labels and are ignored by ingest.

## Per-entity field reality

Entity field semantics, ID prefixes, and enums are defined in `0001`. This section
states only what the **envelope** additionally pins down.

### Required-key strictness at ingest

`kyoko.storage._upsert_row` requires that **every canonical column for an entity be
present as a key in the row**, even nullable ones. A nullable column may be `null`,
but the key must exist. (Inline-payload materialization — below — fills in the
matching `*_ref` key before this check, so a row may instead supply the inline
sibling.) The schema encodes this: each entity lists its canonical columns under
`required`, minus the ref columns that an inline payload can satisfy.

This is stricter than "JSON omits nulls" conventions. Producers must emit the full
key set. The OTLP normalizer and SDK recorder already do.

### Identity and time

- IDs are Kyoko-owned stable strings. `0001` §"Identity And Time" lists the prefix
  convention (`profile_…`, `run_…`, `span_…`, `blob_…`, …). The schema validates IDs
  as **non-empty strings** rather than enforcing the prefix regex, because ingest
  itself is lenient and inline-materialized blob refs use the
  `blob_sha256_<sha-prefix>` form. Treat the prefixes as a producer convention, not an
  ingest gate.
- Timestamps (`created_at`, `started_at`, `ended_at`, `at`, `last_heartbeat_at`, …)
  are **UTC ISO-8601 strings** at the envelope boundary (e.g. `2026-05-31T11:46:00Z`).
  Nullable time columns may be `null`.
- `external_id` carries the source's own stable id when it has one; otherwise `null`.
- `source_id` ties every imported entity back to its `sources` row and therefore its
  `adapter_version` (the source-lineage invariant in `0001`).
- `*_json` columns (`config_json`, `capabilities_json`, `metadata_json`,
  `usage_json`, `attributes_json`) are JSON **objects** in the envelope. Storage
  serializes them to text columns.

### Insertion order and cross-references

Ingest inserts in this dependency order: `profile` → `sources` →
`agent_identities` → `workflow_nodes` → `queues` → `tasks` → `task_attempts` →
`runs` → `spans` → `handoffs` → `timeline_events`. `runs` and `task_attempts`
reference each other; ingest handles this by inserting `task_attempts` with a null
`run_id`, then runs, then back-patching `task_attempts.run_id`. Producers may set
`task_attempts[].run_id` in the envelope; ingest applies it after the run exists.

Foreign keys are enforced (`PRAGMA foreign_keys = ON`). Referenced IDs (e.g. a
span's `run_id`, a run's `agent_identity_id`) must resolve within the same envelope or
already exist in the target DB. The schema does **not** validate referential integrity
— that is enforced by SQLite at ingest and by semantic validation downstream.

## Payload references and inline payloads

Large or sensitive payloads are stored by reference (`0001` design rule 6). Reference
columns hold a `payload_blobs` id (`blob_…`) or `null`. The reference columns are:

| Entity | Ref columns |
|---|---|
| `tasks` | `body_ref` |
| `task_attempts` | `summary_ref`, `error_ref` |
| `runs` | `input_ref`, `output_ref` |
| `spans` | `input_ref`, `output_ref`, `raw_ref` |
| `handoffs` | `reason_ref`, `payload_ref` |
| `timeline_events` | `payload_ref` |

An adapter that has raw data but no pre-registered blob may instead supply an **inline
payload sibling**, which ingest materializes into a content-addressed blob and rewrites
into the matching `*_ref`:

| Ref column | Inline sibling |
|---|---|
| `body_ref` | `body_payload` |
| `summary_ref` | `summary_payload` |
| `error_ref` | `error_payload` |
| `input_ref` | `input_payload` |
| `output_ref` | `output_payload` |
| `raw_ref` | `raw_payload` |
| `reason_ref` | `reason_payload` |
| `payload_ref` | `payload` (handoffs and timeline_events) |

Inline payloads may be a plain string, any JSON value, or a wrapper object with
`content`, `encoding`, `media_type`, `kind`, `redaction_mode`, `retention_days`,
`retained_until`, and `metadata`.

**Mutual exclusion:** a row must not supply both a non-null `*_ref` and its inline
sibling — that makes provenance ambiguous and ingest rejects it
(`…_conflicts_with_…`). The schema encodes this per ref/sibling pair with a `not`
constraint, so the conflict is caught before ingest.

## OTLP mapping

`kyoko.otlp.normalize_otlp_json` consumes OTLP/GenAI JSON
(`resourceSpans` → `scopeSpans` → `spans`, or a flat `spans` list) and emits this
envelope. The mapping follows OTLP GenAI semantic conventions:

- `gen_ai.operation.name` (`invoke_agent`, `execute_tool`, chat/LLM ops) drives the
  canonical span `kind` (`agent` / `tool` / `llm` / …).
- `gen_ai.agent.name` becomes an `agent_identities` row + `workflow_nodes` node; the
  span links to both.
- `gen_ai.request.model` populates the agent's `model`.
- `gen_ai.tool.name` becomes the tool span's `name`.
- OTLP `status.code` (`STATUS_CODE_OK` / `STATUS_CODE_ERROR`) maps to span `status`
  (`succeeded` / `failed`); `error.type` and the rest of the OTLP attributes land in
  `attributes_json`.
- `traceId` groups spans into a `run`; `spanId` / `parentSpanId` build the span tree;
  missing ids are filled by a stable hash. `startTimeUnixNano` / `endTimeUnixNano`
  become ISO-8601.
- Profile id/name/root_path come from `kyoko.profile.*`, `service.namespace`, or
  `service.name` attributes (or the explicit CLI flags).

`tasks`, `task_attempts`, `queues`, and `handoffs` are emitted empty for pure OTLP
trace input — OTLP carries runs and spans, not coordination state.

The raw OTLP fixture
([`../fixtures/source-events/otlp-genai-minimal.json`](../fixtures/source-events/otlp-genai-minimal.json))
is therefore an **input** sample, not an envelope instance. The test suite proves the
contract by normalizing it and validating the *result* against this schema.

## SDK mapping

`kyoko.sdk.KyokoRecorder` is the dependency-free manual wrapper for frameworks with no
native adapter. It records runs/spans/handoffs/timeline events and flushes the same
envelope. `kyoko.span_normalize` provides the SDK-span → canonical
`llm`/`tool`/`other` view used to fill span `kind`, `name`, `usage_json`, and
`attributes_json`. The recorder stays dependency-free; it does **not** depend on this
helper module.

## Validation helper

[`../../kyoko/event_envelope.py`](../../kyoko/event_envelope.py) offers an **optional**
`validate_envelope(obj, *, schema_path=None) -> list[str]` for adapter authors and
tooling that want to fail fast against this schema before calling ingest. It returns a
list of error strings (empty = valid), imports `jsonschema` lazily, and is otherwise
stdlib-only. It is *not* on the ingest hot path — `kyoko.storage` does its own
per-column checks at upsert time. The module also exposes an `EventEnvelope`
documentation dataclass and the `ENVELOPE_COLLECTIONS` / `INLINE_PAYLOAD_SIBLINGS`
constants that mirror `kyoko.storage`.

## What the schema does and does not check

Checks (structural, before ingest):

- `profile` present and well-formed; collections, if present, are arrays of objects.
- Per-entity required key sets, enum-constrained `kind` / `status` fields, JSON-object
  shape for `*_json` columns, ISO-8601-string-typed timestamps.
- Inline-payload / ref mutual exclusion per pair.

Does **not** check (left to ingest / semantic validation):

- Referential integrity across entities (enforced by SQLite foreign keys at ingest).
- ID prefix conventions (producer convention only).
- That referenced blob ids exist (materialized or pre-registered at ingest).
- Timestamp grammar beyond "is a string" (ingest stores text as-is).

## Test coverage

[`../../tests/test_event_envelope.py`](../../tests/test_event_envelope.py) asserts: the
schema is valid draft 2020-12; the Hermes fixture validates clean; the OTLP fixture
validates clean *after normalization*; the default schema lookup resolves; and a set of
deliberately malformed envelopes (missing profile, bad span kind, ref/inline conflict,
non-object root, bad `fixture_version`) each report errors.

## Open decisions

- Whether to bundle the schema under `kyoko/assets/schemas/` and export it via
  `kyoko bundled-assets` (the helper already prefers a bundled copy when present).
- Whether `validate_envelope` should be wired into `kyoko ingest`/`POST /api/ingest`
  as an opt-in pre-flight (today it is opt-in tooling only).
- A dedicated `kyoko.event_envelope.v1` envelope-version field distinct from the
  advisory `fixture_version`, if envelope evolution ever needs it.
