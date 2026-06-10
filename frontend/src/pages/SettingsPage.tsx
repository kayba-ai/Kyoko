import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Settings, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Spinner, ErrorNote, Separator } from "@/components/ui/misc";
import { Tabs } from "@/components/ui/tabs";
import { JsonView } from "@/components/JsonView";
import { fmtBytes } from "@/lib/format";
import { AutonomySettingsPanel } from "./AutonomyPage";
import { AgentKyokoSettingsPanel } from "./McpLogPage";

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
    <div className="flex items-baseline justify-between gap-2 rounded-lg border border-border bg-muted/60 px-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-sm tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function CodeBlock({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-muted p-3 font-mono text-xs text-foreground">
      {children}
    </div>
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
      <CardBody className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Evidence is redacted by a single global default before it leaves the machine (operator prompts,
          MCP, API). Payload references are hidden and sensitive values are scrubbed; pure-local reads are
          unaffected. There is no per-profile policy or audit ledger.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <StatRow label="Payload access" value="redacted" />
          <StatRow label="Redact sensitive values" value="on" />
        </div>
        <div>
          <div className="mb-2 text-sm text-muted-foreground">Sensitive key patterns</div>
          <div className="flex flex-wrap gap-1.5">
            {SENSITIVE_KEY_PATTERNS.map((p) => (
              <Badge key={p} tone="neutral" className="font-mono normal-case tracking-normal">
                {p}
              </Badge>
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
      <CardBody className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Kyoko never auto-deletes. Old evidence is pruned manually, on demand, with an age cutoff:
        </p>
        <CodeBlock>kyoko prune-retention --older-than-days N</CodeBlock>
        <p className="text-sm text-muted-foreground">
          Runs dry by default; pass <span className="font-mono text-foreground">--apply</span> to delete.
          Learning artifacts and replay dependencies are protected from pruning.
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
      <CardBody className="flex flex-col gap-3">
        {scalarEntries.length > 0 && (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
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
            {scalarEntries.length > 0 && <Separator />}
            <JsonView data={rest} />
          </>
        )}
      </CardBody>
    </Card>
  );
}

type SettingsTab = "general" | "autonomy" | "agent-kyoko";

const SETTINGS_TABS: { value: SettingsTab; label: string; path: string; description: string }[] = [
  {
    value: "general",
    label: "General",
    path: "/settings",
    description: "Redaction and retention posture for this machine's single workflow profile.",
  },
  {
    value: "autonomy",
    label: "Autonomy",
    path: "/settings/autonomy",
    description: "Choose human-in-the-loop or autonomous behavior and review recent activity.",
  },
  {
    value: "agent-kyoko",
    label: "Agent ↔ Kyoko",
    path: "/settings/agent-kyoko",
    description: "Live JSON-RPC traffic between a coding agent and Kyoko's MCP server.",
  },
];

function tabFromPath(pathname: string): SettingsTab {
  if (pathname === "/settings/autonomy") return "autonomy";
  if (pathname === "/settings/agent-kyoko") return "agent-kyoko";
  return "general";
}

function GeneralSettingsPanel() {
  const storage = useApi(() => api.storageReport(), []);

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {storage.loading && !storage.data ? (
        <div className="flex h-full items-center justify-center">
          <Spinner />
        </div>
      ) : storage.error ? (
        <ErrorNote error={storage.error} />
      ) : (
        <div className="flex max-w-3xl flex-col gap-6">
          <div className="flex items-center gap-2 rounded-lg border border-primary/25 bg-primary/10 px-3 py-2 text-sm text-primary">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            <span>Loopback by default; non-loopback binds require a Kyoko auth token.</span>
          </div>
          <RedactionCard />
          <RetentionCard />
          <StorageCard data={storage.data} />
        </div>
      )}
    </div>
  );
}

export function SettingsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPath(location.pathname);
  const active = SETTINGS_TABS.find((t) => t.value === tab) ?? SETTINGS_TABS[0];

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Settings"
        description={active.description}
        icon={<Settings className="h-5 w-5" />}
      >
        <Tabs
          tabs={SETTINGS_TABS.map(({ value, label }) => ({ value, label }))}
          value={tab}
          onChange={(next) => {
            const target = SETTINGS_TABS.find((t) => t.value === next);
            if (target) navigate(target.path);
          }}
          variant="segment"
        />
      </PageHeader>
      {tab === "general" && <GeneralSettingsPanel />}
      {tab === "autonomy" && <AutonomySettingsPanel />}
      {tab === "agent-kyoko" && <AgentKyokoSettingsPanel />}
    </div>
  );
}
