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
  if (error instanceof ApiError) {
    const detail = isObj(error.detail) ? error.detail.detail : null;
    return typeof detail === "string" && detail ? detail : error.message;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

function operatorErrorMessage(error: unknown, target: AgentTarget): string {
  const message = errMessage(error);
  if (message === "profile_required") {
    return "Kyoko needs a profile before it can register an operator. Add traces first, then register the agent as a proposal writer.";
  }
  if (message.startsWith("operator_preset_command_not_found:")) {
    const command = message.split(":")[1] || target;
    return `Kyoko could not find \`${command}\` on the PATH used by this dashboard server. Install ${target === "codex" ? "Codex" : "Claude Code"}, or restart \`kyoko serve\` from a shell where \`${command}\` works.`;
  }
  return message;
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

function StepSection({
  step,
  active,
  done,
  label,
  detail,
  icon,
  onToggle,
  children,
}: {
  step: number;
  active: boolean;
  done: boolean;
  label: string;
  detail: string;
  icon: React.ReactNode;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <StepButton
        step={step}
        active={active}
        done={done}
        label={label}
        detail={detail}
        icon={icon}
        onClick={onToggle}
      />
      {active && <div className="pl-0 sm:pl-11">{children}</div>}
    </section>
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

function DetailsBox({ result }: { result: Obj | null }) {
  const [open, setOpen] = React.useState(false);
  if (!result) return null;
  return (
    <div className="flex flex-col gap-2">
      <Button type="button" size="sm" variant="ghost" className="self-start" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide details" : "Having trouble? Show details"}
      </Button>
      {open && <ResultBox result={result} />}
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

function BootstrapSummary({ result }: { result: Obj | null }) {
  if (!result) return null;
  const registered = listFrom(result, "registered");
  const skipped = listFrom(result, "skipped");
  if (registered.length === 0 && skipped.length === 0) return null;
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
      {registered.length > 0 && (
        <div className="text-ok">
          Registered {registered.map((item) => String(item.adapter_id ?? item.name ?? "operator")).join(", ")}
        </div>
      )}
      {skipped.length > 0 && (
        <div className="text-muted-foreground">
          Skipped {skipped.map((item) => `${String(item.adapter_id ?? "operator")} (${String(item.reason ?? "not available")})`).join(", ")}
        </div>
      )}
    </div>
  );
}

async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}

function CopyCommand({ command, onCopied }: { command: string; onCopied?: () => void }) {
  const [copyStatus, setCopyStatus] = React.useState<"idle" | "copied" | "failed">("idle");

  return (
    <div className="flex flex-col gap-2">
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
            if (!command) return;
            try {
              await copyText(command);
              onCopied?.();
              setCopyStatus("copied");
              window.setTimeout(() => setCopyStatus("idle"), 1500);
            } catch {
              setCopyStatus("failed");
            }
          }}
        >
          <Clipboard className="h-3.5 w-3.5" />
          {copyStatus === "copied" ? "Copied" : "Copy"}
        </Button>
      </div>
      {copyStatus === "failed" && (
        <div className="text-xs text-danger">
          Copy failed. Select the command manually.
        </div>
      )}
    </div>
  );
}

function TraceSetup({
  onImported,
  agentTarget,
}: {
  onImported: () => void;
  agentTarget: AgentTarget;
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
  const agentPrompt = `Use Kyoko to finish setup. First call kyoko_discover_sources to check for supported local stores. Then inspect this project and likely local log directories for trace JSON files, especially Kyoko source events, OTLP/GenAI exports, and agent run logs. For every credible JSON trace file you find, call kyoko_import_trace_file with format "auto". After importing, summarize how many runs/spans were added and any files that looked promising but were not importable.`;

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

        <div className="rounded-lg border border-primary/25 bg-primary/10 p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-foreground">Ask {agentTarget === "codex" ? "Codex" : "Claude"} to find traces</div>
              <div className="mt-1 text-xs text-muted-foreground">
                After MCP is connected, paste this into your local agent so it can search and import files through Kyoko.
              </div>
            </div>
            <Badge tone="primary">MCP</Badge>
          </div>
          <CopyCommand command={agentPrompt} />
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

function AgentSetup({
  target,
  onTargetChange,
  onComplete,
}: {
  target: AgentTarget;
  onTargetChange: (target: AgentTarget) => void;
  onComplete: () => void;
}) {
  const [plan, setPlan] = React.useState<Obj | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function loadPlan(nextTarget = target) {
    setError(null);
    try {
      setPlan(await api.mcpInstallPlan(nextTarget, "user"));
    } catch (err) {
      setError(errMessage(err));
    }
  }

  React.useEffect(() => {
    void loadPlan(target);
  }, [target]);

  const command = commandText(plan);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect agent to Kyoko</CardTitle>
        <Badge tone={command ? "ok" : "neutral"}>{target}</Badge>
      </CardHeader>
      <CardBody className="flex flex-col gap-4">
        <Select
          value={target}
          onChange={(next) => onTargetChange(next as AgentTarget)}
          options={[
            { value: "codex", label: "Codex" },
            { value: "claude", label: "Claude" },
          ]}
          className="w-full sm:w-48"
        />
        <div className="flex flex-col gap-2">
          <div className="text-sm text-muted-foreground">
            Run this in your terminal so {target === "codex" ? "Codex" : "Claude"} can see Kyoko MCP tools.
          </div>
          <CopyCommand command={command} onCopied={onComplete} />
        </div>
        {error && <InlineError message={error} />}
        <DetailsBox result={plan} />
      </CardBody>
    </Card>
  );
}

function ProposalWriterSetup({ target }: { target: AgentTarget }) {
  const [bootstrap, setBootstrap] = React.useState<Obj | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function runBootstrap() {
    setBusy(true);
    setError(null);
    try {
      setBootstrap(await api.bootstrapAdapters(target));
    } catch (err) {
      setError(operatorErrorMessage(err, target));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-medium text-foreground">Enable proposal writer</div>
          <div className="mt-1 text-sm text-muted-foreground">
            Register local {target === "codex" ? "Codex" : "Claude"} so Kyoko can call it later to draft proposals.
          </div>
        </div>
        <Button type="button" onClick={() => void runBootstrap()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
          Register proposal writer
        </Button>
      </div>
      <div className="mt-3 flex flex-col gap-3">
        {error && <InlineError message={error} />}
        <BootstrapSummary result={bootstrap} />
        <DetailsBox result={bootstrap} />
      </div>
    </div>
  );
}

function VerifySetup({ tracesReady, onComplete }: { tracesReady: boolean; onComplete: () => void }) {
  const [doctor, setDoctor] = React.useState<Obj | null>(null);
  const [next, setNext] = React.useState<Obj | null>(null);
  const [busy, setBusy] = React.useState<"doctor" | "next" | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function runDoctor() {
    setBusy("doctor");
    setError(null);
    try {
      setDoctor(await api.doctor({ safe_smokes: false }));
      onComplete();
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
      onComplete();
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
  const [active, setActive] = React.useState<StepKey | null>("agents");
  const [agentTarget, setAgentTarget] = React.useState<AgentTarget>("codex");
  const [agentDone, setAgentDone] = React.useState(false);
  const [verifyDone, setVerifyDone] = React.useState(false);
  const metrics = useApi(() => api.dashboardMetrics(), []);
  const [importBump, setImportBump] = React.useState(0);
  const runs = countValue(metrics.data as Obj | null, "runs.total", "total");
  const dashboardMetrics = metrics.data as Obj | null;
  const runStats = isObj(dashboardMetrics?.runs) ? dashboardMetrics.runs : null;
  const traceCount = countValue(runStats, "total") || runs || importBump;
  const tracesReady = traceCount > 0;
  const setupDone = agentDone && tracesReady && verifyDone;

  React.useEffect(() => {
    if (importBump > 0) metrics.reload();
  }, [importBump]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Setup"
        description="Connect an agent, bring traces in, and verify the first useful Kyoko loop."
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
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
            <StepSection
              step={1}
              active={active === "agents"}
              done={agentDone}
              label="Connect agent"
              detail="Codex or Claude through MCP"
              icon={<Terminal className="h-4 w-4" />}
              onToggle={() => setActive((current) => (current === "agents" ? null : "agents"))}
            >
              <AgentSetup
                target={agentTarget}
                onTargetChange={setAgentTarget}
                onComplete={() => setAgentDone(true)}
              />
            </StepSection>
            <StepSection
              step={2}
              active={active === "traces"}
              done={tracesReady}
              label="Add traces"
              detail={tracesReady ? `${traceCount} runs available` : "Upload, scan, or ask the agent"}
              icon={<Upload className="h-4 w-4" />}
              onToggle={() => setActive((current) => (current === "traces" ? null : "traces"))}
            >
              <TraceSetup agentTarget={agentTarget} onImported={() => setImportBump((n) => n + 1)} />
            </StepSection>
            <StepSection
              step={3}
              active={active === "verify"}
              done={verifyDone}
              label="Verify"
              detail="Readiness and next action"
              icon={<ShieldCheck className="h-4 w-4" />}
              onToggle={() => setActive((current) => (current === "verify" ? null : "verify"))}
            >
              <VerifySetup tracesReady={tracesReady} onComplete={() => setVerifyDone(true)} />
            </StepSection>
            {setupDone && (
              <Card>
                <CardBody className="flex flex-col gap-3">
                  <div className="text-sm font-medium text-foreground">First useful loop</div>
                  <div className="text-sm text-muted-foreground">
                    Traces are available and setup checks have run. Start analysis to surface issues.
                  </div>
                  <ProposalWriterSetup target={agentTarget} />
                  <Link to="/analysis" className={buttonVariants({ variant: "outline" })}>
                    Open analysis
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </CardBody>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
