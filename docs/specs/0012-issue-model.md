# 0012 - Issue Model

Status: implemented (schema version 23) — superseded/updated by [0016-issue-centric-loop.md](0016-issue-centric-loop.md)
Date: 2026-06-03

> **Updated by 0016 (schema version 29).** The Issue is no longer a dead-end parallel record:
> it is now the **mandatory origin** of every `LearningProposal` and the central spine of the
> optimization loop. The lifecycle below (`open → resolved/dismissed`) was extended to
> `open → prioritized → diagnosed → proposed → applied → resolved → guarded` (+ `dismissed`),
> with new columns `rank`, `root_cause`, `source`, `evaluator_id`, and a new gate #1
> (issue → proposal). See [0016](0016-issue-centric-loop.md) for the authoritative model.

Initial implementation:

- [`../../kyoko/storage.py`](../../kyoko/storage.py) — `issues` table, schema version 23
- [`../../kyoko/issues.py`](../../kyoko/issues.py) — create/list/get/update-status
- [`../../kyoko/details.py`](../../kyoko/details.py) — `get_issue_detail`
- [`../../kyoko/cli.py`](../../kyoko/cli.py) — `issues`, `issue-detail`, `issue-create`
- [`../../kyoko/web.py`](../../kyoko/web.py) — `GET /api/issues`, `GET /api/issue-detail`, `POST /api/issues`
- [`../../kyoko/mcp.py`](../../kyoko/mcp.py) — `kyoko_list_issues`, `kyoko_get_issue`, `kyoko_create_issue`
- [`../../frontend/src/pages/IssuesPage.tsx`](../../frontend/src/pages/IssuesPage.tsx)
- [`../../tests/test_issues.py`](../../tests/test_issues.py)

## Purpose

An **Issue** is a first-class, durable record of a problem worth tracking — independent
from any `LearningProposal`. Before schema version 23 the only notion of "issue" was a
field on a proposal (`learning_proposals.problem.issue`, `skills.issue`); there was no way
to record a problem that did not yet have a proposed fix, nor to group several proposals
under one tracked problem. This spec closes that gap.

An Issue answers "what is wrong, how bad is it, and what does it touch?" A
`LearningProposal` answers "here is a gated change that might fix it." The two are linked
but distinct: an Issue may have zero, one, or many proposals; a proposal may address an
Issue or stand alone.

## Safety position

Issues are **pure evidence on the read/propose side**. Creating, listing, resolving, or
dismissing an Issue never mutates a skillbook, harness, repo, or autonomy policy and never
bypasses the check/replay gate. Issues therefore sit entirely **outside** the autonomy /
safety boundary, exactly like [annotations](../../kyoko/annotations.py). The MCP write
tool `kyoko_create_issue` is a propose-style write (like `kyoko_annotate` and
`kyoko_submit_proposal`), not a direct-apply or harness-write tool, so it does not appear
in `MCP_DIRECT_APPLY_TOOL_NAMES` / `MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES`.

Single-player invariants from `docs/SCOPE.md` hold: the single implicit profile is
resolved when none is supplied (no profile picker), serving defaults to loopback with
optional token-gated non-loopback binding, and authored content is owned by the single
user. Authored `title`/`body` are **not** redacted (scrubbing the user's own text would be
pointless), but `evidence_refs` are resolved/served through the standard detail path,
which redacts payloads on export.

## Entity

The `issues` table (schema version 23, additive `CREATE TABLE IF NOT EXISTS`, no drop):

| Column | Notes |
|---|---|
| `id` | `issue_{uuid4().hex[:12]}` |
| `profile_id` | FK to `profiles(id)`; single implicit profile resolved when omitted |
| `title` | required, non-empty |
| `body` | nullable free text |
| `section` | nullable; `context \| harness` |
| `category` | nullable free text |
| `severity` | nullable; `low \| medium \| high` |
| `status` | required; `open \| resolved \| dismissed`, default `open` |
| `evidence_refs_json` | list of evidence refs (entity_type/entity_id) |
| `affected_agent_identity_ids_json` | affected `AgentIdentity` ids |
| `affected_workflow_node_ids_json` | affected `WorkflowNode` ids |
| `affected_task_ids_json` | affected `Task` ids |
| `affected_span_ids_json` | affected `Span` ids |
| `proposal_ids_json` | backlinks to `LearningProposal` ids that address this issue |
| `created_at` | UTC ISO-8601 |
| `updated_at` | nullable; set on status transitions |

Indices: `profile_id`, `status`, `section`. `issues` is part of `STATUS_TABLES`, so its
row count appears in `kyoko status --json` counts.

Enums are validated in `kyoko/issues.py`, not in the database (matching the rest of the
schema). Invalid `section`, `severity`, or `status` raise `IssueError`.

## Lifecycle

```
            open ──► resolved
              │  ▲       │
              │  └───────┘
              ▼
          dismissed
```

- New issues default to `open`.
- `update_issue_status(id, status)` moves an issue to any of `open | resolved |
  dismissed` and stamps `updated_at`. Transitions are not one-way; a `resolved` or
  `dismissed` issue may be reopened.

## Relationship to proposals and annotations

- **Proposals**: an Issue links to proposals two ways. (1) **Explicit** backlinks stored
  in `proposal_ids`. (2) **Related** proposals discovered by `get_issue_detail` via
  `_related_proposals_for_entities` — any proposal whose evidence references one of the
  Issue's affected entities (or an evidence ref entity). The detail view tags each linked
  proposal with `link: "explicit" | "related"`.
- **Annotations**: annotations are lightweight markers pinned to a specific run/span;
  Issues are heavier, standalone, lifecycle-bearing records that link multiple entities and
  proposals. Both are evidence and both live outside the gate. An annotation may seed an
  Issue, and an Issue may seed a proposal, but neither changes behavior on its own.

## Detail view

`get_issue_detail(db_path, issue_id)` returns:

- `issue` — the hydrated record.
- `section_label` / `section_description` — present when `section` is set.
- `evidence` — `evidence_refs` resolved via `_resolve_evidence_refs` (redaction on export).
- `affected` — `{agent_identities, workflow_nodes, tasks, spans}`, each a list of
  `{entity_type, entity_id, resolved, found}`.
- `linked_proposals` — explicit + related proposals (deduplicated), each with `link` and
  `matched_evidence_refs`.
- `summary` — counts of evidence refs, resolved refs, affected entities, and linked
  proposals.

## Surfaces

- CLI: `kyoko issues [--status --section --limit] [--json]`,
  `kyoko issue-detail <id> [--json]`,
  `kyoko issue-create <title> [--body --section --category --severity --proposal-id ...] [--json]`.
- API: `GET /api/issues?status=&section=`, `GET /api/issue-detail?id=`,
  `POST /api/issues` (loopback by default; token-gated when bound remotely; JSON
  content-type guard, like `/api/annotations`).
- MCP (read/propose only): `kyoko_list_issues`, `kyoko_get_issue`, `kyoko_create_issue`.
- Dashboard: an **Issues** master/detail worklist mirroring the Proposals page.
