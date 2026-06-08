# Security Policy

This file covers how to **report a vulnerability** in Kyoko. For the product's
runtime safety model (local data, loopback serving, redaction, replay, and write
boundaries), see [docs/SECURITY.md](docs/SECURITY.md).

## Reporting a vulnerability

Please report security issues **privately**. Do not open a public GitHub issue,
pull request, or Discord message for a suspected vulnerability.

Use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, the affected version, and steps to reproduce.

We will acknowledge your report and keep you updated on the fix. Please give us a
reasonable window to address the issue before any public disclosure.

## Supported versions

Kyoko is pre-alpha and ships from `main`. Security fixes are applied to the
latest released version and to `main`; older versions are not separately
maintained.

## Scope

Kyoko is a single-user, local-first tool. It does not implement team auth, RBAC,
multi-tenancy, or cloud workers (see [docs/SCOPE.md](docs/SCOPE.md)). Reports are
most useful when they concern the documented trust boundaries: loopback dashboard
serving and the non-loopback auth token, the proposal/check/replay/apply gate,
evidence redaction, and the handling of external commands you configure.
