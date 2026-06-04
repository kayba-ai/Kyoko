// Small display helpers: relative time, duration between ISO timestamps, byte sizes.

export function parseTs(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? null : ms;
}

export function ago(ts: string | null | undefined, now = Date.now()): string {
  const ms = parseTs(ts);
  if (ms === null) return "—";
  const diff = Math.max(0, now - ms);
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export function durationMs(startedAt: string | null | undefined, endedAt: string | null | undefined): number | null {
  const a = parseTs(startedAt);
  const b = parseTs(endedAt);
  if (a === null || b === null) return null;
  return Math.max(0, b - a);
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m ${rem}s`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const kb = n / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)} MB`;
}

export function fmtTime(ts: string | null | undefined): string {
  const ms = parseTs(ts);
  if (ms === null) return "—";
  return new Date(ms).toLocaleString();
}

/** Compact integer count (1234 -> "1,234"); "—" for null/undefined. */
export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

/** Token count: "—" when null/undefined/0 (we never fabricate zero metrics). */
export function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return "—";
  return n.toLocaleString();
}

/** Percentage like "12%" / "4.5%"; "—" when null/undefined. Sub-10 keeps one
 *  decimal so a small-but-nonzero rate doesn't round to a flat integer. */
export function fmtPercent(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n > 0 && n < 10) return `${n.toFixed(1)}%`;
  return `${Math.round(n)}%`;
}

/** USD cost like "$0.0075"; "—" when null/undefined. */
export function fmtCost(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

const ACRONYMS: Record<string, string> = {
  id: "ID", llm: "LLM", mcp: "MCP", sse: "SSE", json: "JSON", url: "URL",
  ttl: "TTL", api: "API", ms: "ms", l0: "L0", l1: "L1", l2: "L2", l3: "L3",
};

/** snake_case / camelCase / enum string -> Title Case with an acronym map
 *  (id->ID, llm->LLM, mcp->MCP, sse->SSE, json->JSON, url->URL, ...). */
export function humanize(key: string | null | undefined): string {
  if (!key) return "";
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function tryParseJson(s: string | null | undefined): unknown {
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}
