import * as React from "react";
import {
  ArrowRight,
  CheckCircle2,
  Clipboard,
  FileJson,
  Loader2,
  Radio,
  Search,
  ShieldCheck,
  Terminal,
  Upload,
  Wand2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, Spinner } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";

type Obj = Record<string, unknown>;
type ImportMode = "auto" | "source" | "otlp";
type StepKey = "traces" | "agents" | "verify";
type AgentTarget = "codex" | "claude";

function isObj(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function listFrom(data: Obj | null | undefined, key: string): Obj[] {
  const value = data?.[key];
  return Array.isArray(value) ? value.filter(isObj) : [];
}

function countValue(data: Obj | null | undefined, ...keys: string[]): number {
  for (const key of keys) {
    const value = data?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return 0;
}

function errMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

function commandText(plan: Obj | null): string {
  const shell = plan?.shell_command;
  if (typeof shell === "string" && shell) return shell;
  const command = plan?.command;
  return Array.isArray(command) ? command.map(String).join(" ") : "";
}

async function readJsonFile(file: File): Promise<Obj> {
  const text = await file.text();
  const parsed = JSON.parse(text) as unknown;
  if (!isObj(parsed)) throw new Error("JSON root must be an object");
  return parsed;
}

function inferMode(payload: Obj, selected: ImportMode): "source" | "otlp" {
  if (selected !== "auto") return selected;
  if (Array.isArray(payload.resourceSpans) || Array.isArray(payload.scopeSpans)) return "otlp";
  if (payload.fixture_version === "kyoko.source_events.v1" || isObj(payload.source_events)) return "source";
  return "source";
}

function StepButton({
  step,
  active,
  done,
  label,
  detail,
  icon,
  onClick,
}: {
  step: number;
  active: boolean;
  done: boolean;
  label: string;
  detail: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors",
        active ? "border-primary bg-primary/10" : "border-border bg-card hover:bg-accent",
      )}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
          done ? "border-ok/25 bg-ok/10 text-ok" : active ? "border-primary/25 bg-primary/10 text-primary" : "border-border bg-muted text-muted-foreground",
        )}
      >
        {done ? <CheckCircle2 className="h-4 w-4" /> : icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs font-semibold uppercase text-muted-foreground">Step {step}</div>
        <div className="mt-1 font-medium text-foreground">{label}</div>
        <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
      </div>
    </button>
  );
}

function ResultBox({ result }: { result: Obj | null }) {
  if (!result) return null;
  return (
    <div className="rounded-lg border border-border bg-muted/50 p-3">
      <JsonView data={result} />
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm text-danger">
      {message}
    </div>
  );
}

function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted p-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap px-1 font-mono text-xs text-foreground">
        {command || "No native install command for this target yet."}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!command}
        onClick={async () => {
          await navigator.clipboard.writeText(command);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        <Clipboard className="h-3.5 w-3.5" />
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

function TraceSetup({
  onImported,
}: {
  onImported: () => void;
}) {
  const [mode, setMode] = React.useState<ImportMode>("auto");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<Obj | null>(null);
  const [sources, setSources] = React.useState<Obj | null>(null);

  async function importFile(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload = await readJsonFile(file);
      const resolved = inferMode(payload, mode);
      const report = resolved === "otlp" ? await api.ingestOtlp(payload) : await api.ingestSourceEvents(payload);
      setResult({ mode: resolved, ...report });
      onImported();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function scan() {
    setBusy(true);
    setError(null);
    try {
      setSources(await api.discoverSources());
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function importCandidate(candidateId: string) {
    setBusy(true);
    setError(null);
    try {
      const report = await api.importDiscoveredSource({ candidate_id: candidateId });
      setResult(report);
      onImported();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const candidates = listFrom(sources, "candidates");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add traces</CardTitle>
        <Badge tone="primary">Interactive</Badge>
      </CardHeader>
      <CardBody className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_220px]">
          <label className="flex min-h-32 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-6 text-center transition-colors hover:bg-muted/60">
            <Upload className="h-6 w-6 text-primary" />
            <div>
              <div className="text-sm font-medium text-foreground">Choose trace JSON</div>
              <div className="mt-1 text-xs text-muted-foreground">Kyoko source events or OTLP/GenAI JSON</div>
            </div>
            <input
              type="file"
              accept="application/json,.json"
              className="hidden"
              disabled={busy}
              onChange={(event) => void importFile(event.currentTarget.files?.[0] ?? null)}
            />
          </label>
          <div className="flex flex-col gap-3">
            <Select
              value={mode}
              onChange={(next) => setMode(next as ImportMode)}
              disabled={busy}
              options={[
                { value: "auto", label: "Auto-detect" },
                { value: "source", label: "Kyoko events" },
                { value: "otlp", label: "OTLP/GenAI" },
              ]}
            />
            <Button type="button" variant="outline" onClick={() => void scan()} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Scan local sources
            </Button>
          </div>
        </div>

        {error && <InlineError message={error} />}

        {sources && (
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium text-foreground">Discovered sources</div>
            {candidates.length === 0 ? (
              <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                No supported local stores found yet.
              </div>
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                {candidates.map((candidate) => {
                  const id = String(candidate.id ?? "");
                  const status = String(candidate.status ?? "unknown");
                  return (
                    <div key={id} className="flex items-center gap-3 border-b border-border/60 px-3 py-2 last:border-b-0">
                      <FileJson className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground">{String(candidate.label ?? id)}</div>
                        <div className="truncate font-mono text-xs text-muted-foreground">{String(candidate.path ?? "")}</div>
                      </div>
                      <Badge tone={status === "ready" ? "ok" : "neutral"}>{status}</Badge>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy || status !== "ready"}
                        onClick={() => void importCandidate(id)}
                      >
                        Import
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        <ResultBox result={result} />
      </CardBody>
    </Card>
  );
}

function AgentSetup() {
  const [target, setTarget] = React.useState<AgentTarget>("codex");
  const [plan, setPlan] = React.useState<Obj | null>(null);
  const [bootstrap, setBootstrap] = React.useState<Obj | null>(null);
  const [busy, setBusy] = React.useState<"plan" | "bootstrap" | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function loadPlan(nextTarget = target) {
    setBusy("plan");
    setError(null);
    try {
      setPlan(await api.mcpInstallPlan(nextTarget, "user"));
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function runBootstrap() {
    setBusy("bootstrap");
    setError(null);
    try {
      setBootstrap(await api.bootstrapAdapters(target));
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  React.useEffect(() => {
    void loadPlan(target);
  }, [target]);

  const command = commandText(plan);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect Codex or Claude</CardTitle>
        <Badge tone={command ? "ok" : "neutral"}>{target}</Badge>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Select
            value={target}
            onChange={(next) => setTarget(next as AgentTarget)}
            options={[
              { value: "codex", label: "Codex" },
              { value: "claude", label: "Claude" },
            ]}
            className="w-full sm:w-48"
          />
          <Button type="button" variant="outline" onClick={() => void loadPlan()} disabled={busy === "plan"}>
            {busy === "plan" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Terminal className="h-4 w-4" />}
            Refresh command
          </Button>
          <Button type="button" onClick={() => void runBootstrap()} disabled={busy === "bootstrap"}>
            {busy === "bootstrap" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
            Register operator
          </Button>
        </div>
        <CopyCommand command={command} />
        {error && <InlineError message={error} />}
        <ResultBox result={bootstrap ?? plan} />
      </CardBody>
    </Card>
  );
}

function VerifySetup({ tracesReady }: { tracesReady: boolean }) {
  const [doctor, setDoctor] = React.useState<Obj | null>(null);
  const [next, setNext] = React.useState<Obj | null>(null);
  const [busy, setBusy] = React.useState<"doctor" | "next" | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function runDoctor() {
    setBusy("doctor");
    setError(null);
    try {
      setDoctor(await api.doctor({ safe_smokes: false }));
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function planNext() {
    setBusy("next");
    setError(null);
    try {
      setNext(await api.profileNext());
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const readiness = isObj(doctor?.readiness) ? doctor.readiness : null;
  const localReady = readiness?.local_runtime_ready === true;
  const suggestions = listFrom(next, "suggested_commands");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Verify setup</CardTitle>
        <Badge tone={localReady ? "ok" : tracesReady ? "warn" : "neutral"}>
          {localReady ? "ready" : tracesReady ? "check" : "waiting"}
        </Badge>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => void runDoctor()} disabled={busy === "doctor"}>
            {busy === "doctor" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            Run readiness
          </Button>
          <Button type="button" variant="outline" onClick={() => void planNext()} disabled={busy === "next"}>
            {busy === "next" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Plan next step
          </Button>
        </div>
        {error && <InlineError message={error} />}
        {readiness && (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
              <div className="text-xs text-muted-foreground">Runtime</div>
              <div className="mt-1 text-sm font-medium text-foreground">{String(readiness.local_runtime_ready)}</div>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
              <div className="text-xs text-muted-foreground">Local v0</div>
              <div className="mt-1 text-sm font-medium text-foreground">{String(readiness.local_v0_ready)}</div>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 px-3 py-2">
              <div className="text-xs text-muted-foreground">Safe smokes</div>
              <div className="mt-1 text-sm font-medium text-foreground">{String(readiness.safe_smokes_complete)}</div>
            </div>
          </div>
        )}
        {suggestions.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium text-foreground">Next Kyoko action</div>
            {suggestions.slice(0, 3).map((suggestion, index) => (
              <div key={`${suggestion.intent}-${index}`} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                <div className="text-sm font-medium text-foreground">{String(suggestion.label ?? suggestion.intent)}</div>
                <div className="mt-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-muted-foreground">
                  {Array.isArray(suggestion.cli_args) ? suggestion.cli_args.map(String).join(" ") : ""}
                </div>
              </div>
            ))}
          </div>
        )}
        <ResultBox result={next ?? doctor} />
      </CardBody>
    </Card>
  );
}

export function SetupWizardPage() {
  const [active, setActive] = React.useState<StepKey>("traces");
  const metrics = useApi(() => api.dashboardMetrics(), []);
  const [importBump, setImportBump] = React.useState(0);
  const runs = countValue(metrics.data as Obj | null, "runs.total", "total");
  const dashboardMetrics = metrics.data as Obj | null;
  const runStats = isObj(dashboardMetrics?.runs) ? dashboardMetrics.runs : null;
  const traceCount = countValue(runStats, "total") || runs || importBump;
  const tracesReady = traceCount > 0;

  React.useEffect(() => {
    if (importBump > 0) metrics.reload();
  }, [importBump]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Setup"
        description="Bring traces in, connect a local operator, and verify the first useful Kyoko loop."
        icon={<Wand2 className="h-5 w-5" />}
      />
      <div className="flex-1 overflow-y-auto p-6">
        {metrics.loading && !metrics.data ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : metrics.error ? (
          <ErrorNote error={metrics.error} />
        ) : (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
            <aside className="flex flex-col gap-3">
              <StepButton
                step={1}
                active={active === "traces"}
                done={tracesReady}
                label="Add traces"
                detail={tracesReady ? `${traceCount} runs available` : "Upload or scan for local data"}
                icon={<Upload className="h-4 w-4" />}
                onClick={() => setActive("traces")}
              />
              <StepButton
                step={2}
                active={active === "agents"}
                done={false}
                label="Connect agent"
                detail="Codex or Claude through MCP"
                icon={<Terminal className="h-4 w-4" />}
                onClick={() => setActive("agents")}
              />
              <StepButton
                step={3}
                active={active === "verify"}
                done={false}
                label="Verify"
                detail="Readiness and next action"
                icon={<ShieldCheck className="h-4 w-4" />}
                onClick={() => setActive("verify")}
              />
              <Card className="mt-2">
                <CardBody className="flex flex-col gap-3">
                  <div className="text-sm font-medium text-foreground">First useful loop</div>
                  <div className="text-sm text-muted-foreground">
                    Once traces are in, run analysis and review the issues Kyoko finds.
                  </div>
                  <Link to="/analysis" className={buttonVariants({ variant: "outline" })}>
                    Open analysis
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </CardBody>
              </Card>
            </aside>
            <main className="min-w-0">
              {active === "traces" && <TraceSetup onImported={() => setImportBump((n) => n + 1)} />}
              {active === "agents" && <AgentSetup />}
              {active === "verify" && <VerifySetup tracesReady={tracesReady} />}
            </main>
          </div>
        )}
      </div>
    </div>
  );
}
