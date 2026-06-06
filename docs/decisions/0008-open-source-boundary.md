# 0008 - Open-Source Boundary And Distribution

Status: accepted for v0 local runtime
Date: 2026-06-02

## Decision

Kyoko v0 is an Apache-2.0 local-first open-source product. The shipped runtime
is the local CLI, MCP server, dashboard/API, SQLite database, blob store,
integration scaffolds, check/replay engine, measurement plane, and
policy-gated autonomy loop.

Kyoko v0 supports many agents inside one local workflow profile. It may also
list and route multiple local profiles in one database, but it does not ship a
hosted/team product, multi-user workspace, RBAC system, cloud scheduler,
tenant isolation layer, or enterprise governance plane.

Native ACE compatibility is optional. Kyoko may inspect or interoperate with a
user-supplied `ace-framework` package or checkout, but Kyoko does not vendor
ACE, does not make ACE a hard install dependency, and does not require ACE for
the default no-separate-API-key operator-agent path. Kyoko's canonical state,
validation, evals, replay gates, human locks, autonomy policy, and writes
remain Kyoko-owned.

## Distribution

The v0 distribution target is a normal Python source distribution and wheel
with a `kyoko` console script. Package metadata declares Kyoko's license as
Apache-2.0 and includes the bundled schema/demo assets needed for offline
first-run smoke tests.

Optional integrations are runtime integrations, not redistribution claims:

- ACE is loaded or invoked only when a user runs `ace-compat`,
  `ace-diff-proposals`, or `ace-native-run` with an importable package, checkout,
  or user-supplied external ACE command.
- Codex, Claude, Hermes, OpenClaw, and other operator CLIs are discovered or
  registered as local commands owned by the user.
- Framework adapters and replay servers are generated scaffolds or local
  commands, not bundled third-party runtimes.

## Non-Goals

Kyoko v0 does not promise:

- hosted observability,
- team dashboards,
- shared organization accounts,
- cross-user identity proof,
- centralized billing or subscription management,
- remote execution workers,
- arbitrary multi-profile orchestration,
- hard dependency on ACE or any live model provider,
- production-grade multi-tenant isolation.

These can be revisited after the single-player local loop is complete and
validated with real external operators and framework adapters.

## Rationale

The product promise is "make my local agentic workflow better" rather than
"run a hosted observability or agent-management platform." Keeping v0 local and
single-player preserves a simple install path, avoids premature cloud
infrastructure, and keeps autonomy decisions close to the developer's own
workspace and data.

The ACE package currently has distinct runtime and license constraints from
Kyoko's default path. Treating ACE as an optional compatibility boundary lets
Kyoko export/import ACE-shaped data while avoiding accidental coupling between
Kyoko's Apache-2.0 distribution and a user-supplied ACE runtime.

## Evidence

- `setup.cfg` declares `license = Apache-2.0`.
- `pyproject.toml`, `setup.py`, and `MANIFEST.in` define the Python package
  build path and bundled assets.
- `kyoko/ace_bridge.py` only imports ACE through an explicit user-supplied
  package or checkout path.
- `docs/decisions/0004-learning-execution.md` keeps native ACE optional and
  routes all executor outputs through `LearningProposal`.
- `docs/decisions/0007-local-dashboard-auth.md` scopes local dashboard auth
  and explicitly leaves multi-user auth/RBAC out of v0.
- `tests/test_packaging.py` and `kyoko release-smoke` cover wheel/sdist install
  smoke behavior.
- `tests/test_ace_bridge.py` covers the Kyoko-owned ACE import/export
  boundary without requiring ACE as a hard dependency.
