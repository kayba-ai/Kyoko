/**
 * ID + timestamp helpers, mirroring the `_slug`, `_short_id`, and `utc_now`
 * helpers in the Python SDK (kyoko/sdk.py + kyoko/storage.py).
 */

/** Lowercase + non-alphanumeric -> "_", collapse runs, trim, fallback "item". */
export function slug(value: string): string {
  const cleaned = String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return cleaned || "item";
}

/** First 10 hex chars of a random UUID, matching `uuid.uuid4().hex[:10]`. */
export function shortId(): string {
  return randomHex(10);
}

/**
 * UTC timestamp truncated to whole seconds with a trailing "Z", matching the
 * Python `utc_now()`: e.g. "2026-06-03T12:34:56Z".
 */
export function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** Build a prefixed id like `run_my_task_ab12cd34ef`. */
export function newId(prefix: string, name: string): string {
  return `${prefix}_${slug(name)}_${shortId()}`;
}

function randomHex(length: number): string {
  // Prefer the Web Crypto API (Node >=18, browsers, Deno) for unbiased bytes.
  const cryptoObj: Crypto | undefined =
    typeof globalThis !== "undefined"
      ? (globalThis as { crypto?: Crypto }).crypto
      : undefined;
  const byteCount = Math.ceil(length / 2);
  let hex = "";
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    const bytes = new Uint8Array(byteCount);
    cryptoObj.getRandomValues(bytes);
    for (const byte of bytes) {
      hex += byte.toString(16).padStart(2, "0");
    }
  } else {
    // Last-resort fallback; still dependency-free.
    for (let i = 0; i < byteCount; i += 1) {
      hex += Math.floor(Math.random() * 256)
        .toString(16)
        .padStart(2, "0");
    }
  }
  return hex.slice(0, length);
}
