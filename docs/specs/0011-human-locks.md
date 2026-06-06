# 0011 - Human Lock Contract

Status: implemented for v0 safety gates
Date: 2026-06-02

## Purpose

Human locks are Kyoko's explicit "do not change this" mechanism. They are
separate from autonomous policy because a user may want fully autonomous
learning for most surfaces while preserving specific skills, delivery rules,
checks, or harness files.

## Lock Surfaces

| Surface | Canonical state | Blocks writes | Still usable while locked | Reason field |
|---|---|---|---|---|
| Skillbook insight | `skills.human_locked`, `skills.human_lock_reason` | skill update/deactivate/link writes to the same skill id | yes, for context delivery/export | yes |
| Context delivery rule | `context_delivery_rules.human_locked`, `context_delivery_rules.human_lock_reason` | rule update/deactivate writes to the same rule id | yes, for context delivery | yes |
| Check spec | `check_locks` | Kyoko-owned check mutation and trust promotion | yes, check execution may continue | yes |
| Harness target path | `harness_target_locks` | harness prepare and patch apply for the same profile/path | no write; existing file remains untouched | yes |

## Conflict Behavior

Skill conflicts raise `human_locked_skill:<id>` before mutating the canonical
skillbook row. Context delivery rule conflicts raise
`human_locked_context_delivery_rule:<id>` before mutating the canonical rule.

Check specs are different: a lock does not block execution because users may
still want evidence runs against a frozen check. Instead, automatic trust
promotion leaves the canonical `trust_level` unchanged while the lock is
active.

Harness target locks are path-scoped and normalized. A locked target raises
`human_locked_harness_target:<path>` during both harness proposal preparation
and prepared patch transaction apply. This covers autonomous apply after check
gates as well as manual apply.

## Controls

CLI commands:

- `kyoko skill-lock` / `kyoko skill-unlock`
- `kyoko context-rule-lock` / `kyoko context-rule-unlock`
- `kyoko check-lock` / `kyoko check-unlock`
- `kyoko harness-target-lock` / `kyoko harness-target-unlock`
- `kyoko check-locks` / `kyoko harness-target-locks` (list current lock state)

HTTP endpoints:

- `POST /api/skills/lock`
- `POST /api/context-rules/lock`
- `POST /api/check-specs/lock`
- `POST /api/harness-targets/lock`
- `GET /api/check-locks` / `GET /api/harness-target-locks` (list current lock state)

Dashboard controls exist as simple per-entity lock/unlock toggles in the
skillbook, context delivery, check spec, and harness patch panels.

## No History

A human lock is just boolean state plus an optional reason — there is no
lock/unlock event ledger. Lock and unlock operations flip the boolean (or the
lock row) and return a report; they do not write a `timeline_events` row.
Enforcement reads the current boolean/row only. Callers may pass
`actor_agent_identity_id`; Kyoko validates that the actor exists in the same
profile and returns it in the lock/unlock report JSON, but it is not persisted
as a separate audit record. Dashboard callers can set locally persisted `Lock
Actor` and `Lock Reason` values that are included in lock/unlock requests, and
`kyoko serve --default-lock-actor-agent-identity-id` /
`KYOKO_DEFAULT_LOCK_ACTOR_AGENT_IDENTITY_ID` supplies a server-side default
actor when a request omits one (an explicit request actor takes precedence).

## Evidence

Implementation:

- `kyoko/apply.py`
- `kyoko/checks.py`
- `kyoko/harness.py`
- `kyoko/cli.py`
- `kyoko/web.py`

Tests:

- `tests/test_human_locks.py`
- `tests/test_apply.py`
- `tests/test_checks.py`
- `tests/test_harness.py`
- `tests/test_cli.py`
- `tests/test_web.py`

Current direct regression coverage asserts conflict/enforcement behavior for
all four lock surfaces (a locked entity blocks the corresponding autonomy/apply
write). Tests also cover valid actor attribution and invalid actor rejection
for the direct lock APIs, plus CLI/API JSON responses for actor-attributed and
reason-bearing lock changes, and the simple per-entity dashboard lock/unlock
toggles.
