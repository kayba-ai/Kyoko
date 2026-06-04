/**
 * @kyoko/sdk — dependency-free TypeScript SDK for recording agent telemetry
 * into a local Kyoko server. Mirrors the Python SDK in kyoko/sdk.py.
 *
 * Quickstart:
 *
 *   import { KyokoClient, KyokoRecorder } from "@kyoko/sdk";
 *
 *   const recorder = new KyokoRecorder({
 *     profileId: "my-workflow",
 *     profileName: "My Workflow",
 *     rootPath: process.cwd(),
 *   });
 *
 *   const run = recorder.run("nightly summary").start();
 *   const span = run.span("search", { kind: "tool" });
 *   span.finish("succeeded");
 *   run.finish("succeeded", { summary: "done" });
 *
 *   await new KyokoClient().ingest(recorder.toSourceEvents());
 */

export { KyokoClient, KyokoSdkError, DEFAULT_BASE_URL } from "./client.js";
export type { KyokoClientOptions } from "./client.js";

export { KyokoRecorder, RunHandle, SpanHandle } from "./recorder.js";
export type {
  RecorderOptions,
  RunOptions,
  SpanOptions,
} from "./recorder.js";

export { slug, shortId, utcNow, newId } from "./ids.js";

export type {
  JsonValue,
  LiveEvent,
  LiveIngestResponse,
  IngestResponse,
  RunPayload,
  RunStatus,
  SourceEvents,
  SpanPayload,
  SpanStatus,
  TimelineEventPayload,
} from "./types.js";
