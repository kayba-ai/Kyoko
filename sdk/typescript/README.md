# @kyoko/sdk (TypeScript)

A **dependency-free** TypeScript SDK for recording agent telemetry into a local
[Kyoko](https://github.com/kayba-ai/kyoko) server. It mirrors the public surface
of Kyoko's Python SDK (`kyoko/sdk.py`): build runs and spans with a
`KyokoRecorder`, then POST them to a running `kyoko serve` instance with a
`KyokoClient`.

- **No runtime dependencies.** Uses the global `fetch` (Node >= 18, browsers,
  Deno). The only dev dependency is `typescript`.
- **Local-first.** The client defaults to the loopback dashboard/API at
  `http://127.0.0.1:8765`. Nothing is sent off-machine.
- **Same wire format as Python.** `recorder.toSourceEvents()` produces the exact
  `kyoko.source_events.v1` fixture that `POST /api/ingest` accepts.

## Requirements

- Node >= 18 (for global `fetch`).
- A running Kyoko server: `kyoko serve` (see the repo's `docs/INSTALL.md`).

## Install

This package is **not yet published to npm** (publishing is an owner action — see
`docs/INSTALL.md`). For now, build it from this checkout:

```bash
cd sdk/typescript
npm install
npm run build
```

Then reference the built package locally (e.g. `npm install /path/to/sdk/typescript`
or via a workspace).

## Quickstart

```ts
import { KyokoClient, KyokoRecorder } from "@kyoko/sdk";

// 1. Describe who is recording (profile + agent identity).
const recorder = new KyokoRecorder({
  profileId: "my-workflow",
  profileName: "My Workflow",
  rootPath: process.cwd(),
  agentName: "news-researcher",
  model: "gpt-4.1-mini",
});

// 2. Record a run and some spans. Call .start() to open the root agent span.
const run = recorder.run("news summary", {
  inputRef: "prompt://news/topic",
});
run.start();

const search = run.span("searchNews", { kind: "tool" });
try {
  // ... do real work, attach usage/attributes/output as you go ...
  search.finish("succeeded", "output://news/results");
  run.finish("succeeded", { summary: "Summarized today's headlines." });
} catch (err) {
  search.fail(err);
  run.fail(err);
}

// 3. Persist everything into the local Kyoko server.
const client = new KyokoClient(); // http://127.0.0.1:8765 by default
const result = await client.ingest(recorder.toSourceEvents());
console.log(result.profile_id, result.ingested_counts);
```

### Live (push) events

For push observability while a run is in flight, send live events to `/v1/live`:

```ts
await client.ingestLive({
  kind: "log",
  profile_id: "my-workflow",
  run_id: run.runId,
  content: "Fetched 12 articles",
});
```

You can pass a single event or an array.

## API surface

This mirrors `kyoko/sdk.py`:

| TypeScript | Python | Purpose |
| --- | --- | --- |
| `new KyokoRecorder(options)` | `KyokoRecorder(...)` | Accumulate runs/spans in memory. |
| `recorder.run(name, options)` | `recorder.run(...)` | Create a `RunHandle`. |
| `run.start()` | (context-manager `__enter__`) | Open the root agent span. |
| `run.span(name, options)` | `run.span(...)` | Open a child span. |
| `span.finish(status, outputRef)` | `span.finish(...)` | Close a span successfully. |
| `span.fail(error)` | `span.fail(...)` | Close a span as failed (records error attrs). |
| `run.finish(status, {outputRef, summary})` | `run.finish(...)` | Close the run + root span. |
| `run.fail(error)` | `run.fail(...)` | Close the run as failed. |
| `recorder.toSourceEvents()` | `recorder.to_source_events()` | Render the `kyoko.source_events.v1` fixture. |
| `new KyokoClient(baseUrl?)` | `KyokoClient(base_url=...)` | HTTP client. |
| `client.ingest(fixture)` | `client.ingest(...)` | `POST /api/ingest`. |
| `client.ingestLive(events)` | — | `POST /v1/live`. |

### Notes vs. the Python SDK

- TypeScript has no `with` block, so runs/spans are explicit: call `.start()`
  after `recorder.run(...)`, and `.finish()`/`.fail()` yourself (ideally in a
  `try/finally`).
- `KyokoClient` adds `ingestLive(...)` for `/v1/live`; the Python `KyokoClient`
  currently exposes only `ingest(...)`.
- The default `adapter_version` is `kyoko.typescript_sdk.v0`.

## License

Apache-2.0.
