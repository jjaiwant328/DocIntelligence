"use client";

import { useState } from "react";

// ── Reconcile scorecard/findings rendering ──────────────────────────────────
// Status palette (reserved): each state carries an icon + label, never colour
// alone. overall = on_track|at_risk|breach; metric/finding status maps below.
const OVERALL: Record<string, { cls: string; icon: string; label: string }> = {
  on_track: { cls: "bg-green-100 text-green-800", icon: "✓", label: "On track" },
  at_risk:  { cls: "bg-amber-100 text-amber-800", icon: "⚠", label: "At risk" },
  breach:   { cls: "bg-red-100 text-red-800",     icon: "✕", label: "Breach" },
};
const MSTATUS: Record<string, { cls: string; icon: string }> = {
  pass: { cls: "border-green-200 bg-green-50 text-green-700", icon: "✓" },
  warn: { cls: "border-amber-200 bg-amber-50 text-amber-700", icon: "⚠" },
  fail: { cls: "border-red-200 bg-red-50 text-red-700",       icon: "✕" },
};
const SEV: Record<string, { cls: string; label: string }> = {
  high:   { cls: "bg-red-100 text-red-700",   label: "High" },
  medium: { cls: "bg-amber-100 text-amber-700", label: "Medium" },
  low:    { cls: "bg-gray-100 text-gray-600", label: "Low" },
};

interface Metric { name?: string; value?: number | string; unit?: string; target?: string; status?: string }
interface Scorecard { overall?: string; metrics?: Metric[] }
interface Finding { check?: string; severity?: string; detail?: string; amount_impact?: number; subject_doc?: string; reference_doc?: string }

function fmtMetricValue(m: Metric): string {
  const v = m.value;
  if (v == null) return "—";
  const u = m.unit || "";
  if (u === "$") return `$${Number(v).toLocaleString()}`;
  if (u === "%") return `${v}%`;
  return `${v}${u && u !== "count" ? ` ${u}` : ""}`;
}

function ScorecardCard({ sc }: { sc: Scorecard }) {
  const ov = OVERALL[String(sc.overall ?? "").toLowerCase()] ?? OVERALL.on_track;
  const metrics = Array.isArray(sc.metrics) ? sc.metrics : [];
  return (
    <div className="mt-1 rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Scorecard</span>
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1 ${ov.cls}`}>
          <span aria-hidden>{ov.icon}</span> {ov.label}
        </span>
      </div>
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {metrics.map((m, i) => {
            const st = MSTATUS[String(m.status ?? "").toLowerCase()];
            return (
              <div key={i} className={`rounded-lg border px-2.5 py-2 ${st ? st.cls : "border-gray-200 bg-gray-50 text-gray-700"}`}>
                <div className="flex items-center justify-between gap-1">
                  <span className="text-[10px] font-medium opacity-70 truncate">{cap(String(m.name ?? ""))}</span>
                  {st && <span className="text-[11px] font-bold" aria-label={m.status}>{st.icon}</span>}
                </div>
                <div className="text-base font-bold leading-tight">{fmtMetricValue(m)}</div>
                {m.target ? <div className="text-[10px] opacity-60">target {m.target}</div> : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FindingsList({ findings }: { findings: Finding[] }) {
  return (
    <div className="mt-1">
      <div className="text-xs font-semibold text-gray-500 mb-1">Findings ({findings.length})</div>
      <ul className="space-y-1">
        {findings.map((f, i) => {
          const sev = SEV[String(f.severity ?? "").toLowerCase()] ?? SEV.low;
          const impact = typeof f.amount_impact === "number" && f.amount_impact > 0
            ? `$${f.amount_impact.toLocaleString()}` : null;
          return (
            <li key={i} className="flex items-start gap-2 text-xs">
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0 ${sev.cls}`}>{sev.label}</span>
              <span className="text-gray-700 flex-1">
                {f.check ? <span className="font-semibold text-gray-800">{cap(String(f.check))}: </span> : null}
                {f.detail ?? ""}
              </span>
              {impact && <span className="text-[11px] font-bold text-red-600 flex-shrink-0">{impact}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Human-readable formatter for skill outputs. Doc-reading skills return a small
 * set of well-known shapes (doc_type/confidence, entities[], dates[], summary,
 * changes[]…); render those nicely and fall back to pretty JSON for the rest.
 */
export function FormattedOutputs({ skill, outputs }: {
  skill?: string;
  outputs?: Record<string, unknown> | null;
}) {
  const [raw, setRaw] = useState(false);
  if (!outputs || Object.keys(outputs).length === 0) {
    return <p className="text-xs text-gray-400 mt-1">No output.</p>;
  }

  const chips = (items: string[]) => (
    <span className="flex flex-wrap gap-1 mt-0.5">
      {items.map((c, i) => (
        <span key={i} className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{c}</span>
      ))}
    </span>
  );

  const blocks: React.ReactNode[] = [];

  // reconcile_documents: scorecard (status stat tiles) + severity-tagged findings
  if (outputs.scorecard && typeof outputs.scorecard === "object" && !Array.isArray(outputs.scorecard)) {
    blocks.push(<ScorecardCard key="scorecard" sc={outputs.scorecard as Scorecard} />);
  }
  const reconcileFindings = Array.isArray(outputs.findings) &&
    (outputs.findings as Finding[]).some((f) => f && typeof f === "object" && ("check" in f || "severity" in f));
  if (reconcileFindings) {
    blocks.push(<FindingsList key="findings" findings={outputs.findings as Finding[]} />);
  }

  // classification: doc_type + confidence
  if (typeof outputs.doc_type === "string") {
    const conf = typeof outputs.confidence === "number" ? ` (${Math.round(outputs.confidence * 100)}%)` : "";
    blocks.push(
      <Field key="doc_type" label="Classified as">
        <span className="font-medium text-gray-800">{String(outputs.doc_type)}</span>
        <span className="text-gray-400">{conf}</span>
      </Field>
    );
  }
  // summary
  if (typeof outputs.summary === "string" && outputs.summary.trim()) {
    blocks.push(<Field key="summary" label="Summary"><span className="text-gray-700">{outputs.summary}</span></Field>);
  }
  // entities: [{name,type}]
  if (Array.isArray(outputs.entities)) {
    const ents = outputs.entities as { name?: string; type?: string }[];
    blocks.push(
      <Field key="entities" label={`Entities (${ents.length})`}>
        {chips(ents.map((e) => `${e.name ?? ""}${e.type ? ` · ${e.type}` : ""}`))}
      </Field>
    );
  }
  // dates: [{date,role,label}]
  if (Array.isArray(outputs.dates)) {
    const dates = outputs.dates as { date?: string; role?: string; label?: string }[];
    blocks.push(
      <Field key="dates" label={`Dates (${dates.length})`}>
        <ul className="mt-0.5 space-y-0.5">
          {dates.map((d, i) => (
            <li key={i} className="text-gray-700">
              <span className="font-mono">{d.date}</span>
              {d.label ? ` — ${d.label}` : ""}{d.role && d.role !== "other" ? ` (${d.role})` : ""}
            </li>
          ))}
        </ul>
      </Field>
    );
  }
  // create_action: the ids of the actions this step created. Skip when the full
  // `actions` objects are present (the list below renders them meaningfully).
  if (Array.isArray(outputs.action_ids) && (outputs.action_ids as unknown[]).length
      && !Array.isArray(outputs.actions)) {
    const ids = (outputs.action_ids as unknown[]).map(String);
    blocks.push(<Field key="action_ids" label={`Actions created (${ids.length})`}>{chips(ids)}</Field>);
  }

  // requirements / assessments / gaps / changes / proposed_actions / actions: arrays of objects or strings
  const listKeys = ["requirements", "assessments", "gaps", "changes", "proposed_actions", "actions", "events"];
  if (!reconcileFindings) listKeys.push("findings");   // else the ScorecardCard/FindingsList own it
  for (const key of listKeys) {
    if (Array.isArray(outputs[key])) {
      const arr = outputs[key] as unknown[];
      blocks.push(
        <Field key={key} label={`${cap(key)} (${arr.length})`}>
          <ul className="mt-0.5 space-y-0.5">
            {arr.slice(0, 12).map((it, i) => (
              <li key={i} className="text-gray-700">• {summarizeItem(it)}</li>
            ))}
            {arr.length > 12 && <li className="text-gray-400">…and {arr.length - 12} more</li>}
          </ul>
        </Field>
      );
    }
  }
  // everything else — render cleanly by shape so nothing falls back to raw JSON
  const handled = new Set(["doc_type", "confidence", "summary", "entities", "dates", "evidence",
    "scorecard", "action_ids", ...listKeys, "findings"]);
  for (const [k, v] of Object.entries(outputs)) {
    if (handled.has(k) || v == null) continue;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      blocks.push(<Field key={k} label={cap(k)}><span className="text-gray-700">{String(v)}</span></Field>);
    } else if (Array.isArray(v)) {
      const arr = v as unknown[];
      const allScalar = arr.every((it) => typeof it === "string" || typeof it === "number");
      blocks.push(
        <Field key={k} label={`${cap(k)} (${arr.length})`}>
          {allScalar ? chips(arr.map(String)) : (
            <ul className="mt-0.5 space-y-0.5">
              {arr.slice(0, 12).map((it, i) => <li key={i} className="text-gray-700">• {summarizeItem(it)}</li>)}
              {arr.length > 12 && <li className="text-gray-400">…and {arr.length - 12} more</li>}
            </ul>
          )}
        </Field>
      );
    } else if (typeof v === "object") {
      blocks.push(<Field key={k} label={cap(k)}><span className="text-gray-700">{summarizeItem(v)}</span></Field>);
    }
  }

  return (
    <div className="mt-1">
      {!raw && blocks.length > 0 ? <div className="space-y-1">{blocks}</div>
        : blocks.length === 0 ? <p className="text-xs text-gray-400">No structured output.</p>
        : <pre className="text-xs bg-gray-50 rounded p-2 overflow-x-auto">{JSON.stringify(outputs, null, 2)}</pre>}
      {blocks.length > 0 && (
        <button onClick={() => setRaw((v) => !v)} className="mt-1 text-[10px] text-gray-400 hover:text-gray-600">
          {raw ? "▸ formatted view" : "▸ raw JSON"}
        </button>
      )}
    </div>
  );
}

// ── Run-level report ────────────────────────────────────────────────────────
// Deterministic, LLM-free assembly from a run's steps: a status headline, stat
// tiles, the executive narrative, the reconcile scorecard, and findings. Renders
// for EVERY run (old or new) from the stored steps — this is the clean, readable
// view that replaces the raw step/JSON dump in Executions.
interface ReportStep { id: string; skill: string; status: string; outputs?: Record<string, unknown> | null }
interface ReportRun { template_id?: string; status?: string; steps?: ReportStep[] }

function StatTile({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <div className={`rounded-lg border px-2.5 py-1.5 ${tone === "bad" ? "border-red-200 bg-red-50" : "border-gray-200 bg-white"}`}>
      <div className="text-[10px] font-medium uppercase tracking-wide text-gray-400">{label}</div>
      <div className={`text-base font-bold leading-tight ${tone === "bad" ? "text-red-700" : "text-gray-800"}`}>{value}</div>
    </div>
  );
}

export function RunReport({ run }: { run: ReportRun }) {
  const steps = run.steps || [];
  const reconcile = steps.find((s) => s.outputs && typeof s.outputs.scorecard === "object" && !Array.isArray(s.outputs.scorecard));
  const sc = reconcile?.outputs?.scorecard as Scorecard | undefined;
  const findings = (steps
    .flatMap((s) => (Array.isArray(s.outputs?.findings) ? (s.outputs!.findings as Finding[]) : []))
    .filter((f) => f && typeof f === "object" && ("check" in f || "severity" in f)));
  const summaryStep = steps.find((s) => typeof s.outputs?.summary === "string" && (s.outputs!.summary as string).trim());
  const summary = summaryStep?.outputs?.summary as string | undefined;
  const actions = steps
    .flatMap((s) => (Array.isArray(s.outputs?.actions) ? (s.outputs!.actions as ActionItem[]) : []))
    .filter((a) => a && typeof a === "object");
  let actionCount = actions.length;
  if (!actionCount) steps.forEach((s) => { if (Array.isArray(s.outputs?.action_ids)) actionCount += (s.outputs!.action_ids as unknown[]).length; });
  const totalImpact = findings.reduce((sum, f) => sum + (typeof f.amount_impact === "number" ? f.amount_impact : 0), 0);
  const errored = steps.filter((s) => s.status === "error").length;
  const ov = sc?.overall ? OVERALL[String(sc.overall).toLowerCase()] : undefined;

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-3 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Report</span>
        {ov && (
          <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1 ${ov.cls}`}>
            <span aria-hidden>{ov.icon}</span> {ov.label}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
        <StatTile label="Steps" value={String(steps.length)} />
        {findings.length > 0 && <StatTile label="Findings" value={String(findings.length)} />}
        {actionCount > 0 && <StatTile label="Actions" value={String(actionCount)} />}
        {totalImpact > 0 && <StatTile label="$ Impact" value={`$${totalImpact.toLocaleString()}`} tone="bad" />}
        {errored > 0 && <StatTile label="Errors" value={String(errored)} tone="bad" />}
      </div>
      {summary && <p className="text-xs text-gray-700 mb-2 whitespace-pre-wrap">{summary}</p>}
      {sc && <ScorecardCard sc={sc} />}
      {findings.length > 0 && <FindingsList findings={findings} />}
      {actions.length > 0 && <ActionsList actions={actions} />}
    </div>
  );
}

interface ActionItem { action_id?: string; action_type?: string; description?: string; priority?: string; status?: string }

function prioCls(p?: string): string {
  const s = String(p || "").toUpperCase();
  if (s === "HIGH" || s === "CRITICAL") return "bg-red-100 text-red-700";
  if (s === "LOW") return "bg-gray-100 text-gray-600";
  return "bg-amber-100 text-amber-800";  // MEDIUM
}

function ActionsList({ actions }: { actions: ActionItem[] }) {
  return (
    <div className="mt-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
        Actions ({actions.length})
      </div>
      <ul className="space-y-1">
        {actions.map((a, i) => (
          <li key={a.action_id || i} className="text-xs flex items-start gap-2">
            <span className="font-mono text-[10px] bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 shrink-0">
              {cap(String(a.action_type || "review"))}
            </span>
            <span className="text-gray-700 flex-1">{a.description || "—"}</span>
            {a.priority && <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${prioCls(a.priority)}`}>{a.priority}</span>}
            {a.status && <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0 bg-gray-100 text-gray-600">{a.status}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="text-xs">
      <span className="font-semibold text-gray-500">{label}: </span>
      {children}
    </div>
  );
}

function cap(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function summarizeItem(it: unknown): string {
  if (it == null) return "—";
  if (typeof it === "string" || typeof it === "number") return String(it);
  if (typeof it === "object") {
    const o = it as Record<string, unknown>;
    const primary = o.description ?? o.name ?? o.title ?? o.requirement ?? o.text ?? o.change ?? o.finding;
    if (primary) return String(primary);
    return Object.entries(o).slice(0, 3).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
  }
  return String(it);
}
