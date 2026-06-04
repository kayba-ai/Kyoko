/**
 * KyokoClient — a dependency-free HTTP client for a local Kyoko server.
 *
 * Mirrors the Python SDK's `KyokoClient` (kyoko/sdk.py):
 *   - `ingest(...)`     -> POST /api/ingest      (a kyoko.source_events.v1 fixture)
 *   - `ingestLive(...)` -> POST /v1/live         (push live events)
 *
 * Uses the global `fetch` (Node >= 18, browsers, Deno). No runtime dependencies.
 * The server is loopback-only by default (http://127.0.0.1:8765) and every
 * request sends `Content-Type: application/json`, which the server requires.
 */

import type {
  IngestResponse,
  LiveEvent,
  LiveIngestResponse,
  SourceEvents,
} from "./types.js";

export const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

/** Raised when the client cannot reach Kyoko or the server returns an error. */
export class KyokoSdkError extends Error {
  readonly status?: number;
  readonly detail?: string;

  constructor(message: string, options: { status?: number; detail?: string; cause?: unknown } = {}) {
    super(message);
    this.name = "KyokoSdkError";
    this.status = options.status;
    this.detail = options.detail;
    if (options.cause !== undefined) {
      (this as { cause?: unknown }).cause = options.cause;
    }
  }
}

export interface KyokoClientOptions {
  baseUrl?: string;
  /** Per-request timeout in milliseconds (default 10000). */
  timeoutMs?: number;
  /**
   * Optional fetch implementation override (mainly for tests). Defaults to the
   * global `fetch`.
   */
  fetch?: typeof fetch;
}

export class KyokoClient {
  readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(baseUrl: string = DEFAULT_BASE_URL, options: KyokoClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? baseUrl).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? 10_000;
    const resolved = options.fetch ?? (globalThis as { fetch?: typeof fetch }).fetch;
    if (typeof resolved !== "function") {
      throw new KyokoSdkError(
        "global fetch is not available; use Node >= 18 or pass options.fetch",
      );
    }
    this.fetchImpl = resolved;
  }

  /** Persist a `kyoko.source_events.v1` fixture via `POST /api/ingest`. */
  async ingest(sourceEvents: SourceEvents): Promise<IngestResponse> {
    return this.post<IngestResponse>("/api/ingest", sourceEvents);
  }

  /**
   * Send one or more live events via `POST /v1/live`. Accepts a single event or
   * an array; the server also accepts a single-event body or an `{events: [...]}`
   * envelope, but we always send the explicit `{events: [...]}` form.
   */
  async ingestLive(events: LiveEvent | LiveEvent[]): Promise<LiveIngestResponse> {
    const list = Array.isArray(events) ? events : [events];
    return this.post<LiveIngestResponse>("/v1/live", { events: list });
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (cause) {
      const reason =
        cause instanceof Error && cause.name === "AbortError"
          ? `timeout after ${this.timeoutMs}ms`
          : String(cause);
      throw new KyokoSdkError(`kyoko_ingest_unreachable:${reason}`, { cause });
    } finally {
      clearTimeout(timer);
    }

    const text = await response.text();
    if (!response.ok) {
      throw new KyokoSdkError(`kyoko_ingest_failed:${response.status}:${text}`, {
        status: response.status,
        detail: text,
      });
    }
    if (text.length === 0) {
      return {} as T;
    }
    try {
      return JSON.parse(text) as T;
    } catch (cause) {
      throw new KyokoSdkError("kyoko_ingest_bad_json_response", { detail: text, cause });
    }
  }
}
