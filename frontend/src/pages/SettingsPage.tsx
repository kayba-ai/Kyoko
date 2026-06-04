import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner, ErrorNote, Separator } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { fmtBytes } from "@/lib/format";

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function unwrap(data: Obj | null, ...keys: string[]): Obj {
  if (!data) return {};
  for (const k of keys) {
    if (isObj(data[k])) return data[k] as Obj;
  }
  return data;
}

function omit(obj: Obj, keys: string[]): Obj {
  const out: Obj = {};
  for (const [k, v] of Object.entries(obj)) {
    if (!keys.includes(k)) out[k] = v;
  }
  return out;
}

function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  if (!s) return key;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function scalar(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function isByteKey(key: string): boolean {
  const k = key.toLowerCase();
  return k.includes("bytes") || k.includes("size");
}

function StatRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-xs tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-label text-muted-foreground">
      {children}
    </span>
  );
}

// Redaction is a single global "redact on export" default (no per-profile policy,
// no audit ledger — SCOPE simplification). These are the fixed defaults applied
// before evidence leaves the machine; mirror kyoko/redaction.DEFAULT_REDACTION_POLICY.
const SENSITIVE_KEY_PATTERNS = [
  "api_key",
  "apikey",
  "authorization",
  "client_secret",
  "access_key",
  "refresh_token",
  "secret",
  "password",
  "passwd",
  "pwd",
  "token",
  "credential",
  "private_key",
  "cookie",
];

function RedactionCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Redaction</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-3 text-xs text-muted-foreground/80">
          Evidence is redacted by a single global default before it leaves the machine (operator prompts,
          MCP, API). Payload references are hidden and sensitive values are scrubbed; pure-local reads are
          unaffected. There is no per-profile policy or audit ledger.
        </p>
        <div className="flex flex-col gap-1.5">
          <StatRow label="Payload access" value="redacted" />
          <StatRow label="Redact sensitive values" value="on" />
        </div>
        <div className="mt-3">
          <div className="mb-1.5 text-xs text-muted-foreground">Sensitive key patterns</div>
          <div className="flex flex-wrap gap-1">
            {SENSITIVE_KEY_PATTERNS.map((p) => (
              <Chip key={p}>{p}</Chip>
            ))}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function RetentionCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Retention</CardTitle>
      </CardHeader>
      <CardBody>
        <p className="mb-2 text-xs text-muted-foreground/80">
          Kyoko never auto-deletes. Old evidence is pruned manually, on demand, with an age cutoff:
        </p>
        <Chip>kyoko prune-retention --older-than-days N</Chip>
        <p className="mt-2 text-label text-muted-foreground/70">
          Runs dry by default; pass <span className="font-mono">--apply</span> to delete. Learning artifacts
          and replay dependencies are protected from pruning.
        </p>
      </CardBody>
    </Card>
  );
}

function StorageCard({ data }: { data: Obj | null }) {
  const report = unwrap(data, "report", "storage", "storage_report");
  const scalarEntries = Object.entries(report).filter(
    ([, v]) => typeof v === "number" || typeof v === "string" || typeof v === "boolean",
  );
  const rest = omit(
    report,
    scalarEntries.map(([k]) => k),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Storage</CardTitle>
      </CardHeader>
      <CardBody>
        {scalarEntries.length > 0 && (
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {scalarEntries.map(([k, v]) => (
              <StatRow
                key={k}
                label={humanize(k)}
                value={isByteKey(k) && typeof v === "number" ? fmtBytes(v) : scalar(v)}
              />
            ))}
          </div>
        )}
        {Object.keys(rest).length > 0 && (
          <>
            {scalarEntries.length > 0 && <Separator className="my-3" />}
            <JsonView data={rest} />
          </>
        )}
      </CardBody>
    </Card>
  );
}

export function SettingsPage() {
  const storage = useApi(() => api.storageReport(), []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Settings</h1>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {storage.loading && !storage.data ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : storage.error ? (
          <ErrorNote error={storage.error} />
        ) : (
          <div className="flex max-w-3xl flex-col gap-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground/80">
              <ShieldCheck className="h-3.5 w-3.5" />
              <span>Redaction and retention posture for this machine's single workflow profile.</span>
            </div>
            <RedactionCard />
            <RetentionCard />
            <StorageCard data={storage.data} />
            <p className="text-label text-muted-foreground/70">
              Loopback-only, no auth — one user on their own machine is the trust model.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
