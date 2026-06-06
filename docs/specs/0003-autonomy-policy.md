# Spec 0003 - Autonomy Policy

> **SUPERSEDED (2026-06-05) by [0018](0018-two-mode-autonomy-rebuild.md).** The trust ladder
> (L0–L3), the three-way off/propose/autonomous per-section modes, and check/replay as the
> apply gate described here were removed. Autonomy is now one global `mode ∈ {hitl,
> autonomous}`; gate #1 fires on production recurrence, gate #2 is post-hoc (auto-apply + the
> guard monitor rolls back a confirmed regression).

Status: draft gate artifact — updated by [0016-issue-centric-loop.md](0016-issue-centric-loop.md)
Date: 2026-05-31
Blocks: G4, G5, Q5, Q6, Q28, Q29, Q30, Q31, Q32

> **Updated by 0016.** This spec describes the proposal → apply gate ("gate #2"), which is
> unchanged. [0016](0016-issue-centric-loop.md) adds a second gate ("gate #1": issue →
> proposal) that **reuses the `context_mode` / `harness_mode` modes defined here** as a
> generate / no-generate decision (`off` = stop at diagnosed, `propose`/`autonomous` =
> generate). Gate #1 adds no new policy surface.

Initial implementation:

- [`../../kyoko/storage.py`](../../kyoko/storage.py) creates a default per-profile
  autonomy policy with `context_mode = propose` and skillbook writes enabled.
- [`../../kyoko/autonomy.py`](../../kyoko/autonomy.py) exposes policy read/update
  helpers used by CLI, API, and dashboard controls.
- [`../../kyoko/autonomy_runner.py`](../../kyoko/autonomy_runner.py) evaluates
  proposal gates, generates missing check specs for eligible context and harness
  proposals, applies context proposals only after the configured check gate
  passes, and prepares harness patch transactions without autonomous repo
  writes.
- [`../../kyoko/apply.py`](../../kyoko/apply.py) enforces the context policy
  boundary before applying a `skillbook_update` proposal.
- [`../../kyoko/harness.py`](../../kyoko/harness.py) enforces the harness
  propose boundary before creating a reviewable `patch_transactions` row.
- [`../../kyoko/checks.py`](../../kyoko/checks.py) enforces `allow_check_write`
  before creating check specs and rejects unsafe replay side-effect modes.
- [`../../tests/test_apply.py`](../../tests/test_apply.py)
- [`../../tests/test_harness.py`](../../tests/test_harness.py)
- [`../../tests/test_checks.py`](../../tests/test_checks.py)
- [`../../tests/test_autonomy_runner.py`](../../tests/test_autonomy_runner.py)

## Purpose

Kyoko supports autonomous learning, but autonomy is scoped. The user can choose
context autonomy, harness autonomy, both, or neither. When a boundary is enabled
and eligible, Kyoko should act autonomously inside that boundary. When a
proposal fails eligibility, Kyoko must fall back to propose/review state.

> **Scope note (see `docs/SCOPE.md`).** Kyoko is single-player and models exactly one
> agentic workflow. "Profile" / "per-profile" below refers to that **single implicit
> workspace** — there are no multiple, user-selectable profiles. There is one global
> autonomy policy. The wording is kept for storage/FK reasons only and must not surface as
> a profile picker in the CLI, dashboard, or API.
>
> **Replay is required for harness autonomy, not for context autonomy.** Context changes
> gate on a trust ≥ L1 check and never require replay; the "Replay side-effect mode" row in
> the context table only constrains the mode *if* a replay-backed check happens to be used
> (`none` — i.e. no replay — is allowed and is the common case). Harness changes gate on
> trust ≥ L2, which is regression proof and therefore does require replay.

## Modes

Each profile has two independent modes:

```text
context_mode = off | propose | autonomous
harness_mode = off | propose | autonomous
```

Meaning:

- `off`: do not generate or apply proposals for that section.
- `propose`: generate proposals, but require human apply.
- `autonomous`: apply proposals automatically when all gates pass.

Autonomous mode is not a permission to ignore gates. It means no repeated
manual approval is needed after the user has configured the boundary and the
proposal is eligible.

## Context Autonomy

Context autonomy may write:

- Kyoko canonical skillbook rows.
- ACE-compatible skillbook exports owned by Kyoko.
- Kyoko-owned context delivery config.
- Kyoko-owned check specs when `allow_check_write = true`.

Context autonomy may not write:

- arbitrary harness code
- source repo files outside Kyoko-owned context config
- human-locked skill wording
- human-locked context delivery rules
- human-locked check specs
- human-locked harness target paths
- protected paths
- autonomy policy

Minimum gates:

| Gate | Required |
|---|---|
| Valid proposal JSON | yes |
| Evidence references exist | yes |
| No human lock conflict | yes; applied skill/rule locks are enforced by `kyoko/apply.py`; check-spec locks block Kyoko-owned check mutation |
| Section is `context` | yes |
| Check level | `L1_repeated` or stronger unless repeated trace evidence policy allows fallback |
| Replay | **not required for context**; if a replay-backed check is used, mode must be `none`, `filesystem_read`, or `network_mocked` |
| Rollback | previous skill/context version recorded |

Human-locked check specs may still be executed for evidence, but automatic trust
promotion must leave their canonical `trust_level` unchanged.

If `rollback_on_regression = true`, later autonomy runs scan applied context
proposals. When the latest active proposal-linked check run has status `failed`,
Kyoko rolls back skillbook changes through `skill_revisions` and context
delivery rule changes through `context_delivery_rule_revisions`, then marks the
proposal `failed`. Create rollback deactivates the created skill or rule while
preserving audit history. Human-locked skills or rules block automatic rollback.

## Harness Autonomy

Harness autonomy may write:

- allowlisted repo paths
- allowlisted generated harness directories
- Kyoko-owned replay-server harness files
- Kyoko-owned check harness files

The runtime supports harness **prepare** mode for all harness patch kinds and
manual apply/rollback for `generated_file` and `unified_diff` patch
transactions. Apply requires an explicit workspace root, checks the dirty
worktree policy when the workspace is a Git repo, requires
`allow_repo_patch = true`, writes only allowed targets, and captures preimages
for rollback. Generated-file content and unified-diff additions are scanned for
common secret assignments and token formats before repository writes.
`command_plan` remains review-only. In `harness_mode=autonomous`, the autonomy
runner may apply eligible `generated_file` and strict `unified_diff`
transactions only after the required check/replay gate passes and a workspace
root is available from the run request or profile.

If `rollback_on_regression = true`, later autonomy runs scan applied harness
proposals. When the latest active proposal-linked check run has status `failed`,
Kyoko rolls back applied patch transactions through their stored
`rollback_json` preimages and recorded workspace roots, then marks the proposal
`failed`. Harness rollback is intentionally limited to patch transactions;
context rollback is handled separately through skill and context delivery rule
revision ledgers.

Harness autonomy may not write:

- protected paths
- secrets and secret-looking generated content
- dependency lockfiles unless explicitly allowed
- files outside the profile root
- files with unresolved human locks
- git history
- autonomy policy

Minimum gates:

| Gate | Required |
|---|---|
| Valid proposal JSON | yes |
| Evidence references exist | yes |
| Section is `harness` | yes |
| Patch transaction exists | yes |
| Base git SHA recorded | yes |
| Dirty worktree policy passes | yes |
| Protected paths untouched | yes |
| Allowed paths matched | yes |
| Secret scan passes | yes |
| Check level | `L2_regression` or `L3_human_approved` |
| Replay side-effect mode | `sandbox` with `network_mocked`, or stricter |
| Rollback | file preimages or reverse patch recorded |
| File limit | within policy |
| Byte limit | within policy |

## Check Trust Levels

| Level | Meaning | Can gate context autonomy | Can gate harness autonomy |
|---|---|---:|---:|
| `L0_generated` | Generated but not proven | no | no |
| `L1_repeated` | Repeatable and tied to evidence | yes | no |
| `L2_regression` | Fails before fix, passes after fix, side effects bounded | yes | yes |
| `L3_human_approved` | Human reviewed and approved as a gate | yes | yes |

Promotion rules:

- Operators cannot self-promote checks.
- A generated check starts at `L0_generated`.
- `L1_repeated` requires stable results across repeated runs.
- `L2_regression` requires fail-before-fix and pass-after-fix evidence.
- `L3_human_approved` requires explicit human approval through
  `kyoko check-approve`, `POST /api/check-specs/approve`, or the dashboard
  `Approve L3` control.

Only `deterministic_assertion` and `regression_replay` check specs are accepted
as autonomy-gate proof. `judge` check specs can execute as recorded verdict
checks and `smoke_run` check specs can execute as informational stored-run or
replay-output checks, but autonomy rejects them with
`unsupported_gate_check_type:judge` or `unsupported_gate_check_type:smoke_run`
even if the check spec is manually approved to `L3_human_approved`.

## Replay Side-Effect Modes

| Mode | Meaning | Allowed for context autonomy | Allowed for harness autonomy |
|---|---|---:|---:|
| `none` | Pure check or static check | yes | yes |
| `filesystem_read` | Reads files but does not write | yes | yes |
| `sandboxed_filesystem` | Writes only in sandbox | yes | yes |
| `network_mocked` | Network calls are mocked or replayed | yes | yes |
| `live_network` | Calls real network/API | no by default | no by default |
| `unknown` | Boundary is unknown | no | no |

## Dirty Worktree Policy

| Policy | Meaning |
|---|---|
| `block` | any dirty worktree blocks harness apply |
| `allow_touched_only` | dirty files are allowed only when the patch does not touch or depend on them |
| `allow` | no dirty-worktree block, only allowed for explicit user override |

Default:

```text
dirty_worktree_policy = block
```

Implemented harness apply behavior:

- `block` runs `git status --porcelain` for the whole workspace and rejects any
  dirty entry.
- `allow_touched_only` runs `git status --porcelain -- <target_paths>` and
  rejects dirty target paths while allowing unrelated dirty files.
- `allow` skips the dirty-worktree check.

## Protected Paths

Default protected paths:

```text
.env
.env.*
secrets/**
**/secrets/**
node_modules/**
.git/**
*.pem
*.key
*.p12
```

Default harness allowed paths:

```text
agents/**
prompts/**
checks/**
tests/**
.kyoko/**
kyoko/**
```

The default allowlist is intentionally narrow. Users may expand it per profile.

## Apply Decision Matrix

| Section | Mode | Proposal valid | Gates pass | Action |
|---|---|---:|---:|---|
| context | off | yes | yes | reject or ignore |
| context | propose | yes | yes | store proposal for review |
| context | autonomous | yes | yes | apply |
| context | autonomous | yes | no | store as gated |
| harness | off | yes | yes | reject or ignore |
| harness | propose | yes | yes | store proposal for review |
| harness | autonomous | yes | yes | prepare patch transaction; repo apply disabled in v0 |
| harness | autonomous | yes | no | store as gated |
| any | any | no | n/a | store as invalid |

## Audit Requirements

Every autonomous action must create timeline events for:

1. proposal received
2. validation passed
3. gates evaluated
4. apply started
5. apply completed or failed
6. rollback completed if rollback occurs

Implemented v0 audit shape: every `kyoko run-autonomy` proposal decision emits
an `autonomy_decision` timeline event with action, reason, before/after state,
required check level, check ids, and applied artifact ids. Proposal detail exposes
these events as `gate_history`. Broader autonomy audit history is exposed
through `kyoko autonomy-events`, `GET /api/autonomy-events`, and the dashboard
`Autonomy History` panel, with filters for event kind, timeline entity type,
and exact proposal id.

Every autonomous action must preserve:

- producer identity
- evidence refs
- policy snapshot
- check run refs
- replay run refs
- patch transaction refs when files are touched
- before/after canonical state refs

## Open Decisions

- Secret scan implementation is currently conservative pattern matching in
  [`../../kyoko/harness.py`](../../kyoko/harness.py); future work can replace
  it with a pluggable scanner if needed.
- Whether repeated trace evidence should ever replace an check spec for context
  autonomy. The current implementation requires a passing check run.
- Whether dependency file edits are allowed in v0 harness autonomy.
- Whether live-network replay can be explicitly enabled per profile.
