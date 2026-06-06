# 0007 - Local Dashboard Binding And Auth

Status: accepted for v0 local runtime
Date: 2026-06-02
Revised: 2026-06-06

## Decision

Kyoko serves the dashboard/API on loopback by default:

```text
http://127.0.0.1:8765
```

Loopback serving does not require authentication. Kyoko is a local, single-user
tool, and the default trust boundary is the user's own machine.

Kyoko may bind to a non-loopback host only when an auth token is configured. The
CLI accepts `--auth-token` or `KYOKO_AUTH_TOKEN`; if a non-loopback host is
selected without a token, the CLI generates a one-time tokenized dashboard URL
for that server process. The lower-level web server rejects non-loopback serving
without a token.

## Token Transport

When token auth is enabled, requests may provide the token through:

- `Authorization: Bearer <token>`,
- `X-Kyoko-Token: <token>`,
- `?token=<token>` on the dashboard URL,
- the `kyoko_token` cookie set after a valid tokenized load.

## CSRF Guard

All mutating `POST` requests must use `Content-Type: application/json`. Other
media types are rejected before endpoint dispatch. Responses set
`X-Content-Type-Options: nosniff`.

This is not a replacement for auth on remote binds. It is a local-server
footgun guard: ordinary cross-origin form posts cannot send JSON without CORS,
and Kyoko does not expose CORS preflight approval.

## Privileged Surfaces

Context apply/rollback, human-lock changes, autonomy runs, harness
prepare/apply/rollback, check/replay generation and execution, source import,
operator runs, storage pruning, and replay-server lifecycle controls all remain
behind the same product safety gates. Authentication answers "may this HTTP
request reach the local API"; autonomy policy and human locks answer "may this
workflow write behavior-changing state."

## Non-Goals

- Hosted or multi-user auth.
- RBAC.
- Organization identity.
- Production-grade tenant isolation.
- Treating a local token as proof of human review.

## Evidence

- `kyoko/web.py` defaults to `DEFAULT_HOST = "127.0.0.1"`.
- `kyoko/web.py` raises `auth_token_required_for_remote_host` for non-loopback
  serving without an auth token.
- `kyoko/cli.py` supports `--host`, `--auth-token`, and `KYOKO_AUTH_TOKEN`.
- `kyoko/web.py` enforces the JSON POST guard and token checks.
