"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useState, useRef, useEffect, useCallback } from 'react';
import Link from "next/link";
import { ArrowLeft, Upload, FileText, Database, Settings, AlertCircle, File, Eye, Play, Loader2, Lightbulb, Save, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { apiCall } from "@/lib/api-config";
import { FloatingTooltip } from "@/components/ui/floating-tooltip";
import { useDomain, DomainInfo } from "@/context/DomainContext";

// Helper function to format state names for better UX
const formatStateName = (state: string): string => {
    const stateMap: Record<string, string> = {
        'BLOCKED': 'PENDING',
        'TERMINATED': 'COMPLETED',
        'SUCCESS': 'SUCCESS',
        'FAILED': 'FAILED',
        'RUNNING': 'RUNNING',
        'PENDING': 'PENDING',
        'TERMINATING': 'FINISHING',
        'CANCELED': 'CANCELED'
    };
    return stateMap[state] || state;
};

// Helper function to calculate duration in seconds
const calculateDuration = (startTime: number | null, endTime: number | null): string => {
    if (!startTime) return '';
    if (!endTime) return '...';
    const durationMs = endTime - startTime;
    const durationSec = Math.round(durationMs / 1000);
    return `${durationSec}s`;
};

interface SelectedFile {
    file: File;
    name: string;
    size: number;
    type: string;
    preview?: string;
    previewUrl?: string;
    isUploaded: boolean;
    ucPath?: string;
    isProcessing: boolean;
    processError?: string;
}

interface WarehouseConfig {
    warehouse_id: string;
    default_warehouse_id: string;
}

interface VolumePathConfig {
    volume_path: string;
    default_volume_path: string;
}

interface DeltaTablePathConfig {
    delta_table_path: string;
    default_delta_table_path: string;
}

// ── Document Library types ────────────────────────────────────────────────────
interface LibraryDoc {
    doc_id: string;
    filename: string;
    doc_type: string;
    doc_type_label: string;
    processed_ts: string;
    char_count: number;
    est_word_count: number;
    text_preview: string;
    extracted_fields: Record<string, string>;
    entity_count: number;
}

// ── Document Library component ────────────────────────────────────────────────
const DOC_TYPE_COLORS: Record<string, string> = {
    supplier_contract:        "bg-blue-100 text-blue-800 border-blue-200",
    bill_of_lading:           "bg-green-100 text-green-800 border-green-200",
    temperature_log:          "bg-orange-100 text-orange-800 border-orange-200",
    certificate_of_analysis:  "bg-teal-100 text-teal-800 border-teal-200",
    quality_incident_report:  "bg-red-100 text-red-800 border-red-200",
    recall_notice:            "bg-rose-100 text-rose-800 border-rose-200",
    email_chain:              "bg-purple-100 text-purple-800 border-purple-200",
    supplier_scorecard:       "bg-indigo-100 text-indigo-800 border-indigo-200",
    inspection_report:        "bg-cyan-100 text-cyan-800 border-cyan-200",
    maintenance_report:       "bg-amber-100 text-amber-800 border-amber-200",
    delivery_exception:       "bg-yellow-100 text-yellow-800 border-yellow-200",
    carrier_sla:              "bg-lime-100 text-lime-800 border-lime-200",
    weather_report:           "bg-sky-100 text-sky-800 border-sky-200",
};

// ── Pipeline Dashboard types ──────────────────────────────────────────────────

type TaskStatus = {
    task_key: string;
    label: string;
    status: string;
    start_time_ms?: number;
    end_time_ms?: number;
    duration_ms?: number;
    run_url?: string;
    error?: string;
};

type PipelineRun = {
    run_id?: number;
    job_name?: string;
    status: string;
    start_time_ms?: number;
    end_time_ms?: number;
    duration_ms?: number;
    run_url?: string;
};

type PipelineData = {
    status: string;
    run_id?: number;
    run_url?: string;
    start_time_ms?: number;
    end_time_ms?: number;
    duration_ms?: number;
    tasks?: TaskStatus[];
    stats?: Record<string, number | null>;
    recent_runs?: PipelineRun[];
    message?: string;
    new_docs_count?: number;
    job_schedule?: string | null;
};

const TASK_STATUS_STYLE: Record<string, { dot: string; text: string; bg: string }> = {
    succeeded: { dot: "bg-green-500", text: "text-green-700", bg: "bg-green-50" },
    running:   { dot: "bg-blue-500 animate-pulse", text: "text-blue-700", bg: "bg-blue-50" },
    failed:    { dot: "bg-red-500",   text: "text-red-700",   bg: "bg-red-50"   },
    skipped:   { dot: "bg-gray-300",  text: "text-gray-400",  bg: "bg-gray-50"  },
    unknown:   { dot: "bg-gray-300",  text: "text-gray-400",  bg: "bg-gray-50"  },
};

function fmtDur(ms?: number | null) {
    if (!ms) return "";
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function fmtMs(ms?: number | null) {
    if (!ms) return "—";
    return new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

type RunMeta = {
    run_id?: number;
    run_url?: string;
    job_id?: number;
    job_name?: string;
    triggered_at: string;
};

function PipelineDashboard({ domainId, onRunComplete }: { domainId: string; onRunComplete: () => void }) {
    const [data,        setData]        = useState<PipelineData | null>(null);
    const [expanded,    setExpanded]    = useState(false);
    const [triggering,  setTriggering]  = useState(false);
    const [runMeta,     setRunMeta]     = useState<RunMeta | null>(null);
    const [lastChecked, setLastChecked] = useState<string>("");
    const [showConfirm, setShowConfirm] = useState(false);
    const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null);
    const idleRef    = useRef<ReturnType<typeof setInterval> | null>(null);
    const prevStatus = useRef<string | null>(null);

    const fetchStatus = useCallback(async () => {
        try {
            const r = await fetch(`/api/docintel/pipeline-status?domain_id=${encodeURIComponent(domainId)}`);
            if (!r.ok) return;
            const d: PipelineData = await r.json();
            setData(d);
            setLastChecked(new Date().toLocaleString("en-US", {
                month: "short", day: "numeric",
                hour: "2-digit", minute: "2-digit",
            }));
            if (d.status === "running") {
                // Active poll every 60s while running
                if (!pollRef.current) pollRef.current = setInterval(fetchStatus, 60000);
                // Stop idle poll while active poll is running
                if (idleRef.current) { clearInterval(idleRef.current); idleRef.current = null; }
            } else {
                // Stop active poll
                if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                // Start idle poll every 5 min to keep "last run" time fresh
                if (!idleRef.current) idleRef.current = setInterval(fetchStatus, 5 * 60 * 1000);
                if (prevStatus.current === "running") {
                    onRunComplete(); // refresh document library
                }
            }
            prevStatus.current = d.status;
        } catch { /* silent */ }
    }, [domainId, onRunComplete]);

    useEffect(() => {
        fetchStatus();
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
            if (idleRef.current) clearInterval(idleRef.current);
        };
    }, [fetchStatus]);

    async function doTriggerPipeline() {
        setShowConfirm(false);
        setTriggering(true);
        try {
            const r = await fetch(`/api/docintel/trigger-pipeline?domain_id=${encodeURIComponent(domainId)}`, { method: "POST" });
            const resp = r.ok ? await r.json() : null;
            if (resp?.success) {
                const meta: RunMeta = {
                    run_id:       resp.run_id,
                    run_url:      resp.run_url,
                    job_id:       resp.job_id,
                    job_name:     resp.job_name,
                    triggered_at: new Date().toLocaleString("en-US", {
                        month: "short", day: "numeric",
                        hour: "2-digit", minute: "2-digit", second: "2-digit",
                    }),
                };
                setRunMeta(meta);
                setData(prev => prev ? { ...prev, status: "running", tasks: [] } : { status: "running" });
                prevStatus.current = "running";
                setExpanded(true);
                if (idleRef.current) { clearInterval(idleRef.current); idleRef.current = null; }
                if (!pollRef.current) pollRef.current = setInterval(fetchStatus, 60000);
            } else {
                const errText = !r.ok ? await r.text() : "Unknown error";
                setData(prev => prev ? { ...prev, status: "error", message: errText } : { status: "error", message: errText });
            }
        } catch (e: unknown) {
            setData(prev => ({ ...(prev ?? { status: "error" }), status: "error", message: String(e) }));
        }
        setTriggering(false);
    }

    const isRunning  = data?.status === "running";
    const neverRun   = !data || data.status === "never_run";
    const stats      = data?.stats ?? {};
    const newDocs    = data?.new_docs_count ?? 0;

    const headerCls  = isRunning                    ? "bg-blue-50  border-blue-200"
                     : data?.status === "succeeded" ? "bg-green-50 border-green-200"
                     : data?.status === "failed"    ? "bg-red-50   border-red-200"
                     : "bg-amber-50 border-amber-200";
    const headerText = isRunning                    ? "text-blue-800"
                     : data?.status === "succeeded" ? "text-green-800"
                     : data?.status === "failed"    ? "text-red-800"
                     : "text-amber-800";

    const statusIcon = isRunning
        ? <span className="inline-block animate-spin text-lg leading-none">⟳</span>
        : data?.status === "succeeded" ? <span className="text-green-600 text-lg">✓</span>
        : data?.status === "failed"    ? <span className="text-red-600 text-lg">✗</span>
        : <span className="text-amber-500 text-lg">○</span>;

    const estimatedMins = newDocs > 0 ? Math.max(5, Math.ceil(newDocs * 1.5)) : 8;

    return (
        <>
        {/* ── Confirmation dialog ── */}
        {showConfirm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
                <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 w-[420px] max-w-[95vw] overflow-hidden">
                    <div className="px-6 pt-5 pb-4">
                        <div className="flex items-start gap-3">
                            <div className="flex-shrink-0 w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xl">
                                ▶
                            </div>
                            <div>
                                <h3 className="text-base font-bold text-gray-900">Start Pipeline Run?</h3>
                                <p className="text-sm text-gray-500 mt-1">
                                    This will launch the <span className="font-semibold text-gray-700">{domainId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span> document intelligence pipeline on Databricks.
                                </p>
                            </div>
                        </div>

                        <div className="mt-4 rounded-xl bg-blue-50 border border-blue-100 px-4 py-3 space-y-2">
                            <div className="flex items-center gap-2 text-sm text-blue-800">
                                <span className="text-blue-500">⏱</span>
                                <span>Estimated duration: <strong>~{estimatedMins}–{estimatedMins + 5} minutes</strong></span>
                            </div>
                            {newDocs > 0 && (
                                <div className="flex items-center gap-2 text-sm text-blue-800">
                                    <span className="text-blue-500">📄</span>
                                    <span><strong>{newDocs} new document{newDocs !== 1 ? "s" : ""}</strong> will be processed (already-processed docs are skipped)</span>
                                </div>
                            )}
                            <div className="flex items-center gap-2 text-sm text-blue-800">
                                <span className="text-blue-500">🔄</span>
                                <span>Stages: PDF parse → classify → extract fields → knowledge graph → vector index → agent</span>
                            </div>
                            <div className="flex items-center gap-2 text-sm text-amber-700">
                                <span>⚠</span>
                                <span>The pipeline runs on Databricks serverless compute. Status will be polled every 60 seconds.</span>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
                        <button
                            onClick={() => setShowConfirm(false)}
                            className="text-sm px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={doTriggerPipeline}
                            className="text-sm font-semibold px-5 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 shadow transition-colors cursor-pointer"
                        >
                            ▶ Start Pipeline
                        </button>
                    </div>
                </div>
            </div>
        )}

        <div className={`rounded-xl border mb-5 overflow-hidden ${headerCls}`}>

            {/* ── Summary row ── */}
            <div className={`flex items-center gap-3 px-4 py-3 ${headerText}`}>
                {statusIcon}
                <div className="flex-1 min-w-0">
                    <span className="text-sm font-semibold">
                        {isRunning && "Pipeline running — parsing, classifying & building knowledge graph…"}
                        {data?.status === "succeeded" && `Last run succeeded · ${fmtMs(data.end_time_ms)} · ${fmtDur(data.duration_ms)}`}
                        {data?.status === "failed"    && `Last run failed · started ${fmtMs(data.start_time_ms)}`}
                        {neverRun                     && "Pipeline not yet run — upload documents then click ▶ Run Pipeline Now"}
                        {data?.status === "error"     && `Status check error: ${data.message ?? ""}`}
                    </span>
                    <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                        {!isRunning && data?.job_schedule && (
                            <span className="text-xs opacity-60">{data.job_schedule}</span>
                        )}
                        {!isRunning && !data?.job_schedule && (
                            <span className="text-xs opacity-60">No schedule set · auto-refreshes every 5 min</span>
                        )}
                        {lastChecked && <span className="text-[10px] opacity-50">Last checked: {lastChecked}</span>}
                        {isRunning && <span className="text-xs opacity-70 animate-pulse">Polling every 60s…</span>}
                        {newDocs > 0 && !isRunning && (
                            <span className="text-[10px] bg-amber-100 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full font-semibold">
                                {newDocs} new doc{newDocs !== 1 ? "s" : ""} waiting
                            </span>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                    {data?.run_url && !isRunning && (
                        <a href={data.run_url} target="_blank" rel="noreferrer"
                           className="text-xs underline opacity-70 hover:opacity-100 whitespace-nowrap">
                            Last run →
                        </a>
                    )}
                    {isRunning && runMeta?.run_url && (
                        <a href={runMeta.run_url} target="_blank" rel="noreferrer"
                           className="text-xs underline opacity-70 hover:opacity-100 whitespace-nowrap">
                            Track in Databricks →
                        </a>
                    )}
                    <button
                        onClick={() => { if (!triggering && !isRunning) setShowConfirm(true); }}
                        disabled={triggering || isRunning}
                        className={`text-xs font-semibold px-3 py-1.5 rounded-lg border transition-all whitespace-nowrap relative
                            ${triggering || isRunning
                                ? "opacity-40 cursor-not-allowed border-current"
                                : newDocs > 0
                                    ? "bg-amber-500 text-white border-amber-600 hover:bg-amber-600 shadow-sm cursor-pointer"
                                    : "bg-white hover:bg-gray-50 border-current shadow-sm cursor-pointer"}`}
                    >
                        {triggering ? "Starting…" : isRunning ? "⟳ Running…" :
                         newDocs > 0 ? `▶ Process ${newDocs} New Doc${newDocs !== 1 ? "s" : ""}` : "▶ Run Pipeline Now"}
                    </button>
                    <button
                        onClick={() => setExpanded(v => !v)}
                        className="text-xs opacity-60 hover:opacity-100 px-2 py-1 rounded"
                        title={expanded ? "Collapse" : "Show details"}
                    >
                        {expanded ? "▲ Hide" : "▼ Details"}
                    </button>
                </div>
            </div>

            {/* ── Stats strip ── */}
            {(stats.docs_parsed != null || stats.entities_created != null) && (
                <div className="grid grid-cols-5 divide-x divide-gray-200 bg-white border-t border-gray-200">
                    {[
                        { label: "Docs Parsed",      val: stats.docs_parsed },
                        { label: "Fields Extracted", val: stats.fields_extracted },
                        { label: "Entities",         val: stats.entities_created },
                        { label: "Relationships",    val: stats.relationships },
                        { label: "Chunks Indexed",   val: stats.chunks_indexed },
                    ].map(({ label, val }) => (
                        <div key={label} className="px-4 py-2 text-center">
                            <p className="text-lg font-bold text-gray-800">
                                {val == null ? <span className="text-sm text-gray-300">—</span> : val.toLocaleString()}
                            </p>
                            <p className="text-[10px] text-gray-400 font-medium">{label}</p>
                        </div>
                    ))}
                </div>
            )}

            {/* ── Expanded detail ── */}
            {expanded && (
                <div className="bg-white border-t border-gray-200 p-4 space-y-4">

                    {/* ── Recent runs history (shown FIRST so user sees context before running) ── */}
                    {data?.recent_runs && data.recent_runs.length > 0 && (
                        <div>
                            <p className="text-xs font-semibold text-gray-600 mb-2">Recent Run History</p>
                            <div className="overflow-hidden rounded-lg border border-gray-100">
                                <table className="w-full text-xs">
                                    <thead className="bg-gray-50 border-b border-gray-100">
                                        <tr>
                                            <th className="text-left px-3 py-1.5 text-gray-400 font-semibold text-[10px] uppercase">Status</th>
                                            <th className="text-left px-3 py-1.5 text-gray-400 font-semibold text-[10px] uppercase">Job</th>
                                            <th className="text-left px-3 py-1.5 text-gray-400 font-semibold text-[10px] uppercase">Started</th>
                                            <th className="text-right px-3 py-1.5 text-gray-400 font-semibold text-[10px] uppercase">Duration</th>
                                            <th className="text-right px-3 py-1.5 text-gray-400 font-semibold text-[10px] uppercase">Run ID</th>
                                            <th className="px-3 py-1.5" />
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.recent_runs.map((run, i) => {
                                            const s = TASK_STATUS_STYLE[run.status] ?? TASK_STATUS_STYLE.unknown;
                                            return (
                                                <tr key={i} className="border-b border-gray-50 last:border-0 hover:bg-gray-50">
                                                    <td className="px-3 py-1.5">
                                                        <div className="flex items-center gap-1.5">
                                                            <div className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                                                            <span className={`font-semibold ${s.text}`}>{run.status}</span>
                                                        </div>
                                                    </td>
                                                    <td className="px-3 py-1.5 text-gray-500 text-[11px]">{run.job_name ?? "—"}</td>
                                                    <td className="px-3 py-1.5 text-gray-600">{fmtMs(run.start_time_ms)}</td>
                                                    <td className="px-3 py-1.5 text-right text-gray-400 font-mono">{fmtDur(run.duration_ms) || "—"}</td>
                                                    <td className="px-3 py-1.5 text-right font-mono text-gray-400 text-[10px]">{run.run_id ?? "—"}</td>
                                                    <td className="px-3 py-1.5 text-right">
                                                        {run.run_url && (
                                                            <a href={run.run_url} target="_blank" rel="noreferrer"
                                                               className="text-blue-500 hover:underline">view →</a>
                                                        )}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* New docs waiting list */}
                    {newDocs > 0 && !isRunning && (
                        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                            <p className="text-xs font-semibold text-amber-800 mb-1">
                                {newDocs} document{newDocs !== 1 ? "s" : ""} in volume not yet processed
                            </p>
                            <p className="text-[10px] text-amber-600">
                                Click ▶ Run Pipeline to classify, extract fields, and build the knowledge graph for these new documents.
                                Already-processed documents will be skipped (incremental mode).
                            </p>
                        </div>
                    )}

                    {/* Live task breakdown */}
                    {data?.tasks && data.tasks.length > 0 && (
                        <div>
                            <p className="text-xs font-semibold text-gray-600 mb-2">
                                Task Progress
                                {isRunning && <span className="ml-2 text-blue-500 font-normal animate-pulse">live</span>}
                            </p>
                            <div className="space-y-1.5">
                                {data.tasks.map(t => {
                                    const s = TASK_STATUS_STYLE[t.status] ?? TASK_STATUS_STYLE.unknown;
                                    return (
                                        <div key={t.task_key} className={`flex items-center gap-3 rounded-lg px-3 py-2 ${s.bg}`}>
                                            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${s.dot}`} />
                                            <span className={`text-xs font-semibold flex-1 ${s.text}`}>{t.label}</span>
                                            {t.duration_ms != null && (
                                                <span className="text-[10px] text-gray-400">{fmtDur(t.duration_ms)}</span>
                                            )}
                                            {t.status === "running" && (
                                                <span className="text-[10px] text-blue-500 animate-pulse">in progress…</span>
                                            )}
                                            {t.status === "failed" && t.error && (
                                                <span className="text-[10px] text-red-600 font-medium max-w-xs truncate" title={t.error}>
                                                    ✗ {t.error.slice(0, 80)}{t.error.length > 80 ? "…" : ""}
                                                </span>
                                            )}
                                            {t.run_url && (
                                                <a href={t.run_url} target="_blank" rel="noreferrer"
                                                   className="text-[10px] text-blue-500 hover:underline shrink-0">
                                                    logs →
                                                </a>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Waiting for first poll when running */}
                    {isRunning && (!data?.tasks || data.tasks.length === 0) && (
                        <p className="text-xs text-blue-600 animate-pulse text-center py-2">
                            Fetching task status… refreshing every 60 seconds
                        </p>
                    )}

                </div>
            )}
        </div>
        </>
    );
}

// ── Domain Schema Setup Wizard ────────────────────────────────────────────────
// Full-featured, gated Step 1 of the Document Intelligence workflow.
// Moved here from Control Tower so it's part of the document processing flow.

// ── Types
interface SchemaExtractField  { name: string; description: string; example: string; }
interface SchemaDocTypeSchema { doc_type: string; fields: SchemaExtractField[]; }

interface VolumeFile { name: string; path: string; size_bytes: number; modified: string | null; }

// ── Domain defaults
const SCHEMA_SC_LABELS = [
  "delivery_receipt","temperature_log","supplier_contract","quality_inspection_report",
  "bill_of_lading","purchase_order","carrier_agreement","corrective_action_report",
];
const SCHEMA_COMPLIANCE_LABELS = [
  "inspection_report","violation_notice","permit_application","permit_renewal",
  "corrective_action_plan","regulatory_correspondence","training_certificate","vendor_audit_report",
];
const SCHEMA_DEFAULT_LABELS = ["document","report","contract","correspondence","form"];

function schemaDefaultLabels(domainId: string) {
  if (domainId === "supply_chain") return SCHEMA_SC_LABELS;
  if (domainId === "compliance")   return SCHEMA_COMPLIANCE_LABELS;
  return SCHEMA_DEFAULT_LABELS;
}

const SCHEMA_SC_PARSE = `When parsing supply chain documents:
- Extract all lot numbers, batch IDs, and SKUs as exact strings
- Record temperatures in both Fahrenheit and Celsius when present
- Flag any reading that exceeds the 40°F threshold as a violation
- Identify all parties (supplier, carrier, DC, retailer) with their IDs
- Capture date/times in ISO format (YYYY-MM-DDTHH:MM:SS)
- Note any contractual references (MSA numbers, SLA clauses)`;

const SCHEMA_COMPLIANCE_PARSE = `When parsing compliance documents:
- Extract all regulatory citations (e.g. "21 CFR 110.35", "FSMA Section 204")
- Record every deadline and effective date in ISO format (YYYY-MM-DD)
- Identify the issuing authority (regulator name, inspector ID, agency)
- Flag severity levels: Class I (most severe), Class II, Class III
- Note corrective action requirements and their deadlines
- Extract permit/license numbers as exact strings
- Identify all parties (store, franchisee, district, operator)`;

// ── Wizard step bar — only Schema Setup + Process Documents
function WizardStepBar({
  activeStep, schemaReady, onStep,
}: {
  activeStep: "schema" | "process" | "library";
  schemaReady: boolean;
  hasProcessedDocs?: boolean;
  onStep: (s: "schema" | "process" | "library") => void;
}) {
  const steps: { id: "schema" | "process"; label: string; icon: string }[] = [
    { id: "schema",  label: "Schema Setup",      icon: "⚙️" },
    { id: "process", label: "Process Documents", icon: "📤" },
  ];
  return (
    <div className="flex items-center gap-0 border-b border-gray-200 bg-white px-6 mb-0">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center">
          <button
            onClick={() => onStep(s.id)}
            className={`flex items-center gap-2 px-5 py-3.5 text-xs font-semibold border-b-2 transition-colors ${
              activeStep === s.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300 cursor-pointer"
            }`}
          >
            <span>{s.icon}</span>
            <span>{s.label}</span>
            {s.id === "schema" && schemaReady && (
              <span className="ml-1 text-[10px] font-bold bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">✓</span>
            )}
          </button>
          {i < steps.length - 1 && (
            <span className="text-gray-200 mx-1 text-sm">›</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Locked step placeholder
function LockedStep({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-80 p-12 text-center bg-gray-50">
      <span className="text-5xl mb-4">🔒</span>
      <h2 className="text-lg font-bold text-gray-700 mb-2">{label} is locked</h2>
      <p className="text-sm text-gray-500 max-w-sm">{reason}</p>
    </div>
  );
}

// ── File drop zone component ──────────────────────────────────────────────────
function FileDropZone({ uploadedFile, onFile }: { uploadedFile: File | null; onFile: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  function acceptFile(f: File) {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (ext === "pdf" || ext === "txt") onFile(f);
  }

  return (
    <div>
      <label className="text-xs font-semibold text-gray-700 mb-1.5 block">Upload a sample file (PDF or TXT)</label>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={e => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
        onDragEnter={e => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setIsDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) acceptFile(f);
        }}
        className={`flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-xl cursor-pointer transition-all select-none outline-none ${
          isDragging   ? "border-blue-500 bg-blue-100 scale-[1.01]" :
          uploadedFile ? "border-blue-400 bg-blue-50" :
                         "border-gray-300 hover:border-blue-400 bg-gray-50 hover:bg-blue-50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) acceptFile(f); e.target.value = ""; }}
        />
        {uploadedFile ? (
          <>
            <span className="text-3xl mb-1">{uploadedFile.name.endsWith(".pdf") ? "📄" : "📝"}</span>
            <p className="text-sm font-semibold text-blue-700">{uploadedFile.name}</p>
            <p className="text-[10px] text-blue-500">{Math.round(uploadedFile.size / 1024)} KB · click or drop to change</p>
          </>
        ) : (
          <>
            <span className={`text-3xl mb-1 transition-transform ${isDragging ? "scale-125" : ""}`}>
              {isDragging ? "📂" : "📁"}
            </span>
            <p className="text-sm text-gray-500">{isDragging ? "Release to upload" : "Drop a file here or click to browse"}</p>
            <p className="text-[10px] text-gray-400">PDF or TXT, up to 10 MB</p>
          </>
        )}
      </div>
    </div>
  );
}

// ── Doc-type step wizard sub-component step bar ──────────────────────────────
function SchemaStepBar({ step }: { step: number }) {
  const steps = ["Doc Type", "Source", "Analyze", "Confirm"];
  return (
    <div className="flex items-center gap-0 mb-6">
      {steps.map((label, i) => {
        const idx = i + 1;
        const done   = step > idx;
        const active = step === idx;
        return (
          <div key={label} className="flex items-center">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
              done   ? "bg-green-100 text-green-700" :
              active ? "bg-blue-600 text-white" :
                       "bg-gray-100 text-gray-400"
            }`}>
              {done ? "✓" : <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${active ? "bg-white text-blue-600" : "bg-gray-300 text-gray-500"}`}>{idx}</span>}
              <span>{label}</span>
            </div>
            {i < steps.length - 1 && (
              <span className={`mx-1 text-sm ${done ? "text-green-300" : "text-gray-200"}`}>›</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Full Domain Schema Setup Wizard ──────────────────────────────────────────
function DomainSchemaWizard({
  domainId, domainName, onSchemaConfirmed,
}: {
  domainId: string;
  domainName: string;
  onSchemaConfirmed: () => void;
}) {
  // ── Domain-level state (fed into handleSave / domain_configs) ─────────────
  const [loading,        setLoading]       = useState(true);
  const [saving,         setSaving]        = useState(false);
  const [savedAt,        setSavedAt]       = useState<string | null>(null);
  const [saved,          setSaved]         = useState(false);
  const [isConfigured,   setIsConfigured]  = useState(false);
  const [labels,         setLabels]        = useState<string[]>([]);
  const [labelExample,   setLabelExample]  = useState<Record<string, string>>({});
  const [schemas,        setSchemas]       = useState<SchemaDocTypeSchema[]>([]);
  const [parseInstr,     setParseInstr]    = useState("");

  // ── Wizard navigation ──────────────────────────────────────────────────────
  type WStep = "list" | "s1_name" | "s2_source" | "s3_confirm";
  const [wStep,     setWStep]    = useState<WStep>("list");
  const [wDocType,  setWDocType] = useState("");   // normalized snake_case
  const [wIsEdit,   setWIsEdit]  = useState(false);

  // ── Step 1: library lookup ─────────────────────────────────────────────────
  const [libStatus,  setLibStatus]  = useState<"idle" | "checking" | "found" | "new">("idle");
  type LibData = { fields: SchemaExtractField[]; description: string; examples: string[]; parse_instructions: string; };
  const [libData,    setLibData]    = useState<LibData | null>(null);

  // ── Step 2: source selection ───────────────────────────────────────────────
  const [sourceMode,       setSourceMode]       = useState<"volume" | "upload">("volume");
  // Volume path for THIS doc type
  const [wizVolPath,       setWizVolPath]       = useState("");
  const [wizVolFiles,      setWizVolFiles]      = useState<VolumeFile[]>([]);
  const [wizVolLoading,    setWizVolLoading]    = useState(false);
  const [wizVolError,      setWizVolError]      = useState<string | null>(null);
  const [wizSelFile,       setWizSelFile]       = useState<string | null>(null);
  const [wizFileSearch,    setWizFileSearch]    = useState("");
  // Dropdown of available UC volumes
  interface AvailableVolume { catalog: string; schema: string; name: string; full_path: string; label: string; }
  const [availVols,        setAvailVols]        = useState<AvailableVolume[]>([]);
  const [availVolsLoading, setAvailVolsLoading] = useState(false);
  const [availVolsError,   setAvailVolsError]   = useState<string | null>(null);
  const [manualVolPath,    setManualVolPath]     = useState("");
  // Direct file upload
  const [uploadedFile,     setUploadedFile]     = useState<File | null>(null);
  const [uploadedFileB64,  setUploadedFileB64]  = useState("");

  // ── Step 2→3: analysis ────────────────────────────────────────────────────
  const [analyzing,      setAnalyzing]     = useState(false);
  interface SuggestedField { name: string; description: string; example_value: string; }
  interface AnalysisResult {
    predicted_doc_type: string;
    extracted_fields: Record<string, string>;
    suggested_new_fields: SuggestedField[];
    parse_flags: string[];
    data_quality_notes?: string[];
    ok?: boolean;
    error?: string;
  }
  const [analysisResult,  setAnalysisResult]  = useState<AnalysisResult | null>(null);
  const [analyzeError,    setAnalyzeError]    = useState<string | null>(null);
  const [selSuggestions,  setSelSuggestions]  = useState<Set<string>>(new Set());

  // ── Step 3: confirm / edit ─────────────────────────────────────────────────
  const [fieldsDraft,         setFieldsDraft]         = useState<SchemaExtractField[]>([]);
  const [classExamples,       setClassExamples]       = useState<string[]>([]);
  const [examplesLoading,     setExamplesLoading]     = useState(false);
  const [parseInstrDraft,     setParseInstrDraft]     = useState("");
  const [hintsLoading,        setHintsLoading]        = useState(false);
  const [showParseEditor,     setShowParseEditor]     = useState(false);
  const [presets,             setPresets]             = useState<Record<string, { display_name: string; description: string; fields: SchemaExtractField[] }>>({});
  const [showPresetMenu,      setShowPresetMenu]      = useState(false);

  // ── Load schema presets ──────────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/docintel/schema-presets")
      .then(r => r.ok ? r.json() : { presets: {} })
      .then(d => setPresets(d.presets ?? {}))
      .catch(() => {});
  }, []);

  // ── Load saved config — merges domain_configs + global doc_type_schemas ───
  useEffect(() => {
    setLoading(true);

    // Load both sources in parallel
    Promise.all([
      fetch(`/api/docintel/domain-schema?domain_id=${domainId}`).then(r => r.json()).catch(() => ({})),
      fetch(`/api/docintel/doc-type-schemas`).then(r => r.json()).catch(() => ({ schemas: [] })),
    ]).then(([d, globalLib]: [Record<string, unknown>, { schemas?: { doc_type: string; display_name?: string; extraction_schema?: string; classification_examples?: string; parse_instructions?: string }[] }]) => {
      // ── Labels from domain_configs ────────────────────────────────────
      let domainLabels: string[] = [];
      const exMap: Record<string, string> = {};
      if (d.classification_labels) {
        try {
          const parsed = JSON.parse(d.classification_labels as string);
          domainLabels = Array.isArray(parsed)
            ? parsed.map((l: unknown) => typeof l === "object" && l !== null
                ? (l as { name?: string }).name ?? String(l) : String(l))
            : Object.keys(parsed);
          if (Array.isArray(parsed)) {
            parsed.forEach((l: unknown) => {
              if (typeof l === "object" && l !== null) {
                const lo = l as { name?: string; example?: string };
                if (lo.name && lo.example) exMap[lo.name] = lo.example;
              }
            });
          }
        } catch { /* ignore */ }
      }

      // ── Labels from global doc_type_schemas library ───────────────────
      const libSchemas = globalLib.schemas || [];
      const libLabels  = libSchemas.map(s => s.doc_type).filter(Boolean);

      // Merge: union of domain labels + library labels (library is authoritative for fields)
      const allLabels = Array.from(new Set([...domainLabels, ...libLabels]));

      // ── Extraction schemas — prefer library fields ────────────────────
      const schMap = new Map<string, SchemaExtractField[]>();
      // First seed from domain_configs
      if (d.extraction_schemas) {
        try {
          const parsed = JSON.parse(d.extraction_schemas as string);
          const arr: SchemaDocTypeSchema[] = Array.isArray(parsed) ? parsed
            : Object.entries(parsed).map(([dt, v]: [string, unknown]) => ({
                doc_type: dt,
                fields: Array.isArray((v as { fields?: unknown[] }).fields)
                  ? (v as { fields: SchemaExtractField[] }).fields : [],
              }));
          arr.forEach(s => { if (s.fields.length > 0) schMap.set(s.doc_type, s.fields); });
        } catch { /* ignore */ }
      }
      // Overlay with library (more detailed)
      libSchemas.forEach(ls => {
        if (ls.extraction_schema) {
          try {
            const fields = JSON.parse(ls.extraction_schema) as SchemaExtractField[];
            if (Array.isArray(fields) && fields.length > 0) schMap.set(ls.doc_type, fields);
          } catch { /* ignore */ }
        }
        // Classification examples → labelExample
        if (ls.classification_examples) {
          try {
            const ex = JSON.parse(ls.classification_examples) as string[];
            if (Array.isArray(ex) && ex[0]) exMap[ls.doc_type] = ex[0];
          } catch { /* ignore */ }
        }
      });

      const merged: SchemaDocTypeSchema[] = allLabels.map(l => ({
        doc_type: l,
        fields: schMap.get(l) ?? [],
      }));

      setLabels(allLabels);
      setLabelExample(exMap);
      setSchemas(merged);
      setIsConfigured(allLabels.length > 0);

      if (d.parse_instructions) setParseInstr(d.parse_instructions as string);
      else setParseInstr(domainId === "supply_chain" ? SCHEMA_SC_PARSE : domainId === "compliance" ? SCHEMA_COMPLIANCE_PARSE : "");
      setSavedAt((d.saved_at as string) ?? null);
    }).catch(() => {
      setLabels(schemaDefaultLabels(domainId));
      setIsConfigured(false);
    }).finally(() => setLoading(false));
  }, [domainId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Domain-level save ──────────────────────────────────────────────────────
  async function handleSave(andConfirm = false) {
    setSaving(true); setSaved(false);
    try {
      const labelsJson  = JSON.stringify(labels.map(l => labelExample[l] ? { name: l, example: labelExample[l] } : l));
      const schemasJson = JSON.stringify(schemas.filter(s => s.fields.length > 0));
      await fetch("/api/docintel/domain-schema", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, classification_labels: labelsJson, extraction_schemas: schemasJson, parse_instructions: parseInstr || null }),
      });
      setSavedAt(new Date().toISOString()); setIsConfigured(labels.length > 0); setSaved(true);
      if (andConfirm && labels.length > 0) { setTimeout(onSchemaConfirmed, 800); }
      else { setTimeout(() => setSaved(false), 3000); }
    } catch { alert("Failed to save schema. Please try again."); }
    finally { setSaving(false); }
  }

  // ── Wizard helpers ─────────────────────────────────────────────────────────
  function removeDocType(dt: string) {
    setLabels(prev => prev.filter(x => x !== dt));
    setSchemas(prev => prev.filter(s => s.doc_type !== dt));
  }

  function startWizard(dt: string, isEdit: boolean) {
    const norm = dt.trim().toLowerCase().replace(/\s+/g, "_");
    setWDocType(norm || "");
    setWIsEdit(isEdit);
    setWStep("s1_name");
    setLibStatus("idle"); setLibData(null);
    setWizVolPath(""); setWizVolFiles([]); setWizSelFile(null);
    setUploadedFile(null); setUploadedFileB64("");
    setAnalysisResult(null); setAnalyzeError(null); setSelSuggestions(new Set());
    // Pre-populate fields draft from existing schema
    const existing = schemas.find(s => s.doc_type === norm);
    setFieldsDraft(existing?.fields ?? []);
    setClassExamples(labelExample[norm] ? [labelExample[norm]] : []);
    setParseInstrDraft("");
    setShowParseEditor(false);
    // If we have a name, look up library immediately
    if (norm) lookupLibrary(norm);
  }

  function lookupLibrary(dt: string) {
    const norm = dt.trim().toLowerCase().replace(/\s+/g, "_");
    if (norm.length < 2) { setLibStatus("idle"); return; }
    setLibStatus("checking");
    fetch(`/api/docintel/doc-type-schema?doc_type=${encodeURIComponent(norm)}`)
      .then(r => r.json())
      .then((d: Record<string, unknown>) => {
        if (d.found && d.extraction_schema) {
          try {
            const fields = JSON.parse(d.extraction_schema as string) as SchemaExtractField[];
            const examples = d.classification_examples ? JSON.parse(d.classification_examples as string) as string[] : [];
            const pi = (d.parse_instructions as string) || "";
            setLibData({ fields, description: (d.description as string) || "", examples, parse_instructions: pi });
            setLibStatus("found");
          } catch { setLibStatus("new"); setLibData(null); }
        } else { setLibStatus("new"); setLibData(null); }
      })
      .catch(() => { setLibStatus("new"); setLibData(null); });
  }

  function loadAvailableVolumes() {
    setAvailVolsLoading(true); setAvailVolsError(null);
    fetch("/api/docintel/list-volumes")
      .then(r => r.json())
      .then((d: Record<string, unknown>) => {
        setAvailVols((d.volumes as AvailableVolume[]) ?? []);
        if (!((d.volumes as unknown[]) ?? []).length)
          setAvailVolsError((d.debug_error as string) ? `No volumes found: ${d.debug_error}` : "No volumes found.");
      })
      .catch(e => setAvailVolsError(String(e)))
      .finally(() => setAvailVolsLoading(false));
  }

  function loadVolFiles(volPath: string) {
    if (!volPath) return;
    setWizVolLoading(true); setWizVolError(null); setWizVolFiles([]); setWizSelFile(null);
    const qs = new URLSearchParams({ domain_id: domainId, volume_path: volPath });
    fetch(`/api/docintel/volume-files?${qs}`)
      .then(r => r.json())
      .then((d: Record<string, unknown>) => {
        setWizVolFiles((d.files as VolumeFile[]) ?? []);
        if (d.message) setWizVolError(d.message as string);
      })
      .catch(e => setWizVolError(String(e)))
      .finally(() => setWizVolLoading(false));
  }

  function handleFileUploadChange(file: File) {
    setUploadedFile(file);
    const reader = new FileReader();
    reader.onload = e => setUploadedFileB64((e.target?.result as string).split(",")[1] ?? "");
    reader.readAsDataURL(file);
  }

  async function runAnalysis() {
    setAnalyzing(true); setAnalyzeError(null); setAnalysisResult(null); setSelSuggestions(new Set());
    try {
      let d: AnalysisResult;
      if (sourceMode === "upload" && uploadedFileB64 && uploadedFile) {
        const res = await fetch("/api/docintel/analyze-uploaded-file", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ doc_type: wDocType, file_name: uploadedFile.name, file_content_b64: uploadedFileB64, file_mime: uploadedFile.type, domain_id: domainId, extraction_schema: JSON.stringify(fieldsDraft) }),
        });
        d = await res.json();
      } else {
        const res = await fetch("/api/docintel/domain-schema-preview", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain_id: domainId, file_name: wizSelFile, volume_path: wizVolPath, extraction_schema: JSON.stringify(fieldsDraft), parse_instructions: parseInstrDraft || null }),
        });
        d = await res.json();
      }
      if (d.error && !d.suggested_new_fields?.length) { setAnalyzeError(d.error); }
      else {
        setAnalysisResult(d);
        setSelSuggestions(new Set((d.suggested_new_fields ?? []).map(f => f.name)));
        // Auto-apply all suggested fields to draft
        const existing = new Set(fieldsDraft.map(f => f.name));
        const toAdd = (d.suggested_new_fields ?? []).map(f => ({ name: f.name, description: f.description, example: f.example_value ?? "" })).filter(f => !existing.has(f.name));
        if (toAdd.length) setFieldsDraft(prev => [...prev, ...toAdd]);
        setWStep("s3_confirm");
      }
    } catch (e) { setAnalyzeError(String(e)); }
    finally { setAnalyzing(false); }
  }

  async function generateExamples() {
    setExamplesLoading(true);
    try {
      const r = await fetch(`/api/docintel/generate-classification-examples?doc_type=${encodeURIComponent(wDocType)}&domain_id=${domainId}`);
      const d: { examples?: string[] } = await r.json();
      setClassExamples(d.examples ?? []);
    } catch { /* ignore */ }
    finally { setExamplesLoading(false); }
  }

  async function generateHints() {
    setHintsLoading(true);
    try {
      const r = await fetch(`/api/docintel/generate-parse-hints?doc_type=${encodeURIComponent(wDocType)}&domain_id=${domainId}`);
      const d: { suggested_instructions?: string } = await r.json();
      setParseInstrDraft(d.suggested_instructions ?? "");
      setShowParseEditor(true);
    } catch { /* ignore */ }
    finally { setHintsLoading(false); }
  }

  async function commitDocType(andProceed: boolean) {
    const norm = wDocType.trim().toLowerCase().replace(/\s+/g, "_");
    if (!norm) return;
    // Update domain-level state
    if (!labels.includes(norm)) setLabels(prev => [...prev, norm]);
    setSchemas(prev => {
      const idx = prev.findIndex(s => s.doc_type === norm);
      if (idx >= 0) return prev.map((s, i) => i === idx ? { ...s, fields: fieldsDraft } : s);
      return [...prev, { doc_type: norm, fields: fieldsDraft }];
    });
    if (classExamples[0]) setLabelExample(prev => ({ ...prev, [norm]: classExamples[0] }));
    if (parseInstrDraft) {
      setParseInstr(prev => {
        const marker = `# ${norm.replace(/_/g, " ")}`;
        return prev.includes(marker) ? prev : prev ? prev.trimEnd() + "\n\n" + parseInstrDraft : parseInstrDraft;
      });
    }
    // Save to global library
    fetch("/api/docintel/doc-type-schema", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_type: norm, extraction_schema: JSON.stringify(fieldsDraft),
        classification_examples: JSON.stringify(classExamples),
        parse_instructions: parseInstrDraft, volume_path: wizVolPath,
        sample_file_path: wizSelFile ? `${wizVolPath}/${wizSelFile}` : (uploadedFile?.name ?? ""),
        domain_id: domainId,
      }),
    }).catch(() => {});
    if (andProceed) {
      // Save everything then proceed
      const updatedLabels = labels.includes(norm) ? labels : [...labels, norm];
      const updatedSchemas = schemas.some(s => s.doc_type === norm)
        ? schemas.map(s => s.doc_type === norm ? { ...s, fields: fieldsDraft } : s)
        : [...schemas, { doc_type: norm, fields: fieldsDraft }];
      const updatedExample = classExamples[0] ? { ...labelExample, [norm]: classExamples[0] } : labelExample;
      setSaving(true);
      try {
        await fetch("/api/docintel/domain-schema", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            domain_id: domainId,
            classification_labels: JSON.stringify(updatedLabels.map(l => updatedExample[l] ? { name: l, example: updatedExample[l] } : l)),
            extraction_schemas: JSON.stringify(updatedSchemas.filter(s => s.fields.length > 0)),
            parse_instructions: parseInstrDraft || parseInstr || null,
          }),
        });
        setIsConfigured(true); setSavedAt(new Date().toISOString());
        setTimeout(onSchemaConfirmed, 600);
      } catch { alert("Failed to save. Please try again."); }
      finally { setSaving(false); }
    } else {
      setWStep("list");
    }
  }

  if (loading) {
    return <div className="text-center py-20 text-gray-400 animate-pulse">Loading schema configuration…</div>;
  }

  // ── Wizard step number helper ─────────────────────────────────────────────
  const wStepNum = wStep === "s1_name" ? 1 : wStep === "s2_source" ? 2 : wStep === "s3_confirm" ? 3 : 0;
  const dtLabel  = wDocType ? wDocType.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "";

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Schema Setup — {domainName}</h1>
            <p className="text-sm text-gray-500 mt-1">
              Build extraction schemas per document type. Each schema is saved to a global library for reuse across all subject areas.
              {isConfigured && savedAt && <span className="ml-2 text-green-600 font-medium">✓ Last saved {new Date(savedAt).toLocaleDateString()}</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {saved && <span className="text-sm text-green-600 font-semibold">✓ Saved!</span>}
            <button
              onClick={() => handleSave(false)}
              disabled={saving}
              className="px-4 py-2 text-sm font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {saving ? "Saving…" : "💾 Save"}
            </button>
            <button
              onClick={() => handleSave(true)}
              disabled={saving || labels.length === 0}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "✅ Proceed to Process Documents →"}
            </button>
          </div>
        </div>

        {/* ════════════════════════════════════════════════════════════════════ */}
        {/*  WIZARD — conditional rendering based on wStep                     */}
        {/* ════════════════════════════════════════════════════════════════════ */}

        {wStep === "list" ? (
          /* ── List view ──────────────────────────────────────────────────── */
          <div className="space-y-4">
            {/* Intro banner */}
            <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-3.5 text-xs text-blue-800 flex items-start gap-4">
              <span className="text-2xl mt-0.5">📋</span>
              <div>
                <p className="font-bold text-blue-900 mb-0.5">Document Type Schema Library</p>
                <p>For each document type in <strong>{domainName}</strong>, configure:</p>
                <p className="mt-1 space-x-3">
                  <span>① <strong>Classification label</strong> — for <code className="bg-blue-100 px-0.5 rounded">ai_classify()</code></span>
                  <span>② <strong>Extraction fields</strong> — for <code className="bg-blue-100 px-0.5 rounded">ai_extract()</code></span>
                  <span>③ <strong>Parse instructions</strong> — for <code className="bg-blue-100 px-0.5 rounded">ai_parse_document()</code></span>
                </p>
                <p className="mt-1 text-blue-600">Schemas are stored globally and shared across all subject areas.</p>
              </div>
            </div>

            {/* Doc type table */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
                <p className="text-sm font-semibold text-gray-800">
                  Configured Document Types
                  <span className="ml-2 text-xs font-normal text-gray-400">({labels.length})</span>
                </p>
                <button
                  onClick={() => startWizard("", false)}
                  className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 flex items-center gap-1"
                >
                  ✚ Add Document Type
                </button>
              </div>

              {labels.length === 0 ? (
                <div className="py-12 text-center text-gray-400">
                  <p className="text-3xl mb-2">📂</p>
                  <p className="text-sm font-medium">No document types yet</p>
                  <p className="text-xs mt-1">Click <strong>✚ Add Document Type</strong> to get started</p>
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-100 text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                      <th className="text-left px-5 py-2.5">Document Type</th>
                      <th className="text-left px-4 py-2.5">Extraction Fields</th>
                      <th className="text-left px-4 py-2.5">Status</th>
                      <th className="px-4 py-2.5"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {labels.map(l => {
                      const sch = schemas.find(s => s.doc_type === l);
                      const fc  = sch?.fields.length ?? 0;
                      return (
                        <tr key={l} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                          <td className="px-5 py-3">
                            <p className="font-mono font-semibold text-gray-800">{l}</p>
                            {labelExample[l] && <p className="text-[10px] text-gray-400 mt-0.5 truncate max-w-xs">{labelExample[l]}</p>}
                          </td>
                          <td className="px-4 py-3">
                            <span className={`font-semibold ${fc > 0 ? "text-violet-600" : "text-gray-400"}`}>
                              {fc > 0 ? `${fc} field${fc !== 1 ? "s" : ""}` : "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            {fc > 0
                              ? <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-green-100 text-green-700">✓ Configured</span>
                              : <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">⚠ Needs fields</span>}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center gap-2 justify-end">
                              <button onClick={() => startWizard(l, true)} className="text-xs text-blue-600 hover:text-blue-800 font-semibold">Edit</button>
                              <button onClick={() => removeDocType(l)} className="text-xs text-gray-300 hover:text-red-500 font-bold">✕</button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>

            {/* Proceed */}
            {labels.length > 0 && (
              <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-5 py-4">
                <div className="text-xs text-gray-500 space-y-0.5">
                  <p><strong>{labels.length}</strong> type{labels.length !== 1 ? "s" : ""} · <strong>{schemas.reduce((n, s) => n + s.fields.length, 0)}</strong> total fields · parse: {parseInstr ? `${parseInstr.length} chars` : "not set"}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleSave(false)} disabled={saving} className="px-4 py-2 text-sm font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                    {saving ? "Saving…" : "💾 Save"}
                  </button>
                  <button onClick={() => handleSave(true)} disabled={saving} className="px-5 py-2 text-sm font-bold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                    {saving ? "Saving…" : "✅ Proceed to Process Documents →"}
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* ── Wizard steps ───────────────────────────────────────────────── */
          <div className="space-y-4">
            {/* Step bar */}
            <SchemaStepBar step={wStepNum} />

            {/* ── Step 1: Document Type Name ──────────────────────────────── */}
            {wStep === "s1_name" && (
              <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
                <div>
                  <h2 className="text-base font-bold text-gray-900">Step 1 — Document Type</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Name the type of document (e.g. <code className="bg-gray-100 px-1 rounded">invoice</code>, <code className="bg-gray-100 px-1 rounded">inspection_report</code>). The system checks the global library for an existing schema.</p>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-700">Document type name</label>
                  <input
                    value={wDocType}
                    onChange={e => {
                      const v = e.target.value.toLowerCase().replace(/\s+/g, "_");
                      setWDocType(v);
                      if (v.length >= 2) lookupLibrary(v);
                      else { setLibStatus("idle"); setLibData(null); }
                    }}
                    placeholder="invoice, purchase_order, inspection_report…"
                    className="w-full text-sm font-mono border-2 border-gray-300 rounded-xl px-4 py-3 focus:outline-none focus:border-blue-500 transition-colors"
                    autoFocus
                  />

                  {/* Library status */}
                  {libStatus === "checking" && (
                    <p className="text-xs text-gray-400 animate-pulse">🔍 Checking global library…</p>
                  )}
                  {libStatus === "found" && libData && (
                    <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3">
                      <span className="text-lg mt-0.5">✅</span>
                      <div className="flex-1">
                        <p className="text-xs font-bold text-emerald-800">Found in global library — {libData.fields.length} extraction fields</p>
                        {libData.description && <p className="text-[10px] text-emerald-600 mt-0.5">{libData.description}</p>}
                        <p className="text-[10px] text-emerald-600 mt-0.5">Fields will be pre-loaded. You can add, edit, or remove them in Step 3.</p>
                      </div>
                    </div>
                  )}
                  {libStatus === "new" && wDocType.length >= 2 && (
                    <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 text-xs text-amber-800">
                      <span>✨</span>
                      <span><strong>New type</strong> — not yet in the library. We&apos;ll build a schema from a sample document in the next step.</span>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between pt-2">
                  <button onClick={() => setWStep("list")} className="text-sm text-gray-500 hover:text-gray-800">← Cancel</button>
                  <button
                    onClick={() => {
                      if (!wDocType.trim()) return;
                      // If library found, pre-populate fields and skip to confirm
                      if (libStatus === "found" && libData) {
                        setFieldsDraft(libData.fields);
                        setClassExamples(libData.examples);
                        setParseInstrDraft(libData.parse_instructions);
                        setWStep("s3_confirm");
                      } else {
                        setWStep("s2_source");
                      }
                    }}
                    disabled={!wDocType.trim() || libStatus === "checking"}
                    className="px-6 py-2.5 text-sm font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
                  >
                    {libStatus === "found" ? "Load from Library →" : "Next: Select Sample Document →"}
                  </button>
                </div>
              </div>
            )}

            {/* ── Step 2: Source — Volume or Upload ───────────────────────── */}
            {wStep === "s2_source" && (
              <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
                <div>
                  <h2 className="text-base font-bold text-gray-900">Step 2 — Sample Document for <span className="font-mono text-blue-700">{dtLabel}</span></h2>
                  <p className="text-xs text-gray-500 mt-0.5">Provide a sample document so the AI can suggest extraction fields. Each document type can have its own volume.</p>
                </div>

                {/* Source mode toggle */}
                <div className="flex gap-3">
                  {(["volume", "upload"] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => setSourceMode(m)}
                      className={`flex-1 flex items-center gap-3 px-4 py-3 rounded-xl border-2 text-left transition-all ${
                        sourceMode === m ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <span className="text-2xl">{m === "volume" ? "📂" : "📤"}</span>
                      <div>
                        <p className="text-sm font-semibold text-gray-800">{m === "volume" ? "From UC Volume" : "Upload a File"}</p>
                        <p className="text-[10px] text-gray-400">{m === "volume" ? "Pick from an existing Unity Catalog volume" : "Upload a PDF or TXT directly from your computer"}</p>
                      </div>
                    </button>
                  ))}
                </div>

                {/* Volume picker */}
                {sourceMode === "volume" && (
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs font-semibold text-gray-700 mb-1.5 block">
                        Unity Catalog Volume for <span className="font-mono text-blue-700">{dtLabel}</span>
                      </label>
                      {/* Volume selector */}
                      <div className="flex gap-2">
                        <select
                          value={wizVolPath}
                          onChange={e => {
                            const p = e.target.value;
                            setWizVolPath(p);
                            if (p) loadVolFiles(p);
                          }}
                          className="flex-1 text-xs font-mono border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
                          onClick={() => { if (!availVols.length && !availVolsLoading) loadAvailableVolumes(); }}
                        >
                          <option value="">— Select a volume —</option>
                          {availVols.map(v => (
                            <option key={v.full_path} value={v.full_path}>{v.label}</option>
                          ))}
                        </select>
                        <button
                          onClick={loadAvailableVolumes}
                          disabled={availVolsLoading}
                          className="px-3 py-2 text-xs font-semibold border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {availVolsLoading ? "…" : "↺"}
                        </button>
                      </div>
                      {/* Manual path fallback */}
                      <div className="flex gap-2 mt-2">
                        <input
                          value={manualVolPath}
                          onChange={e => setManualVolPath(e.target.value)}
                          placeholder="/Volumes/catalog/schema/volume_name"
                          className="flex-1 text-xs font-mono border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-300"
                        />
                        <button
                          onClick={() => { const p = manualVolPath.trim(); if (p) { setWizVolPath(p); loadVolFiles(p); setManualVolPath(""); } }}
                          disabled={!manualVolPath.trim()}
                          className="px-3 py-1.5 text-xs font-semibold border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                        >
                          Use
                        </button>
                      </div>
                      {availVolsError && <p className="text-[10px] text-amber-600 mt-1">{availVolsError}</p>}
                    </div>

                    {/* File list */}
                    {wizVolPath && (
                      <div>
                        <label className="text-xs font-semibold text-gray-700 mb-1.5 block">Select a sample file</label>
                        {wizVolLoading ? (
                          <p className="text-xs text-gray-400 animate-pulse py-2">Loading files…</p>
                        ) : wizVolError ? (
                          <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">{wizVolError}</p>
                        ) : wizVolFiles.length === 0 ? (
                          <p className="text-xs text-gray-400 italic">No PDF or TXT files found in this volume.</p>
                        ) : (
                          <div>
                            {/* Search bar */}
                            {wizVolFiles.length > 5 && (
                              <div className="relative mb-2">
                                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs">🔍</span>
                                <input
                                  type="text"
                                  placeholder="Search files…"
                                  value={wizFileSearch}
                                  onChange={e => setWizFileSearch(e.target.value)}
                                  className="w-full pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
                                />
                                {wizFileSearch && (
                                  <button onClick={() => setWizFileSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-600 text-xs cursor-pointer">✕</button>
                                )}
                              </div>
                            )}
                            <div className="space-y-1.5 max-h-52 overflow-y-auto border border-gray-100 rounded-xl p-2">
                              {wizVolFiles
                                .filter(f => !wizFileSearch || f.name.toLowerCase().includes(wizFileSearch.toLowerCase()))
                                .map(f => {
                                  const isPdf = f.name.toLowerCase().endsWith(".pdf");
                                  return (
                                    <button
                                      key={f.name}
                                      onClick={() => setWizSelFile(f.name)}
                                      className={`w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                                        wizSelFile === f.name ? "bg-blue-50 border border-blue-300" : "border border-gray-100 hover:bg-gray-50"
                                      }`}
                                    >
                                      <span className="text-base">{isPdf ? "📄" : "📝"}</span>
                                      <div className="flex-1 min-w-0">
                                        <p className="text-xs font-mono font-semibold text-gray-800 truncate">{f.name}</p>
                                        <p className="text-[10px] text-gray-400">{f.size_bytes ? `${Math.round(f.size_bytes / 1024)} KB` : ""}{f.modified ? ` · ${new Date(f.modified).toLocaleDateString()}` : ""}</p>
                                      </div>
                                      {wizSelFile === f.name && <span className="text-blue-500 font-bold text-xs">✓</span>}
                                    </button>
                                  );
                                })}
                              {wizVolFiles.filter(f => !wizFileSearch || f.name.toLowerCase().includes(wizFileSearch.toLowerCase())).length === 0 && (
                                <p className="text-xs text-gray-400 text-center py-3 italic">No files match "{wizFileSearch}"</p>
                              )}
                            </div>
                            <p className="text-[10px] text-gray-400 mt-1">
                              {wizVolFiles.filter(f => !wizFileSearch || f.name.toLowerCase().includes(wizFileSearch.toLowerCase())).length} of {wizVolFiles.length} files
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* File upload */}
                {sourceMode === "upload" && (
                  <FileDropZone
                    uploadedFile={uploadedFile}
                    onFile={handleFileUploadChange}
                  />
                )}

                {/* Analyze button */}
                <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                  <button onClick={() => setWStep("s1_name")} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setWStep("s3_confirm")}
                      className="text-xs text-gray-400 hover:text-gray-700 underline"
                    >
                      Skip analysis, set fields manually
                    </button>
                    <button
                      onClick={runAnalysis}
                      disabled={analyzing || (sourceMode === "volume" ? !wizSelFile : !uploadedFile)}
                      className="px-6 py-2.5 text-sm font-bold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 flex items-center gap-2"
                    >
                      {analyzing ? <><span className="animate-spin">⏳</span> Analyzing…</> : "🔍 Analyze with AI →"}
                    </button>
                  </div>
                </div>

                {analyzeError && (
                  <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-xs text-red-700">
                    <p className="font-semibold mb-0.5">Analysis error</p>
                    <p>{analyzeError}</p>
                  </div>
                )}
              </div>
            )}

            {/* ── Step 3: Confirm schema ───────────────────────────────────── */}
            {wStep === "s3_confirm" && (
              <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
                <div>
                  <h2 className="text-base font-bold text-gray-900">Step 3 — Confirm Schema for <span className="font-mono text-blue-700">{dtLabel}</span></h2>
                  <p className="text-xs text-gray-500 mt-0.5">Review and edit the extraction fields, classification examples, and parse instructions.</p>
                </div>

                {/* AI analysis summary */}
                {analysisResult && (
                  <div className="bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-3 text-xs">
                    <p className="font-semibold text-indigo-800 mb-1">🧠 AI Analysis Result</p>
                    <div className="flex flex-wrap gap-3">
                      {analysisResult.predicted_doc_type && (
                        <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-mono">
                          Predicted type: {analysisResult.predicted_doc_type}
                        </span>
                      )}
                      {analysisResult.parse_flags?.map((f, i) => (
                        <span key={i} className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">⚠ {f}</span>
                      ))}
                    </div>
                    {Object.keys(analysisResult.extracted_fields ?? {}).length > 0 && (
                      <details className="mt-2">
                        <summary className="text-indigo-600 cursor-pointer hover:text-indigo-800">▶ Extracted sample values</summary>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1.5">
                          {Object.entries(analysisResult.extracted_fields).map(([k, v]) => (
                            <div key={k} className="flex gap-1.5">
                              <span className="text-gray-400 font-mono">{k}:</span>
                              <span className="text-gray-700 truncate">{v ?? <em className="text-gray-300">null</em>}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}

                {/* Extraction fields editor */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-gray-700">
                      Extraction Fields <span className="text-gray-400 font-normal">(for <code className="bg-gray-100 px-1 rounded">ai_extract()</code>)</span>
                    </p>
                    <div className="flex items-center gap-2">
                      {/* Load Preset dropdown */}
                      {Object.keys(presets).length > 0 && (
                        <div className="relative">
                          <button
                            onClick={() => setShowPresetMenu(v => !v)}
                            className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-indigo-300 text-indigo-700 hover:bg-indigo-50 flex items-center gap-1"
                          >
                            ⚡ Load Preset
                          </button>
                          {showPresetMenu && (
                            <div className="absolute right-0 top-8 z-20 bg-white border border-gray-200 rounded-xl shadow-lg min-w-[240px] overflow-hidden">
                              {Object.entries(presets).map(([key, preset]) => (
                                <button
                                  key={key}
                                  onClick={() => {
                                    // Merge preset fields into fieldsDraft (deduplicate by name)
                                    const existing = new Set(fieldsDraft.map(f => f.name));
                                    const toAdd = preset.fields.filter(f => !existing.has(f.name));
                                    setFieldsDraft(prev => [...prev, ...toAdd]);
                                    setShowPresetMenu(false);
                                  }}
                                  className="w-full text-left px-4 py-3 hover:bg-indigo-50 border-b border-gray-100 last:border-0"
                                >
                                  <p className="text-xs font-semibold text-gray-800">{preset.display_name}</p>
                                  <p className="text-[10px] text-gray-400 mt-0.5">{preset.description}</p>
                                  <p className="text-[10px] text-indigo-600 mt-0.5">{preset.fields.length} fields</p>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      <button
                        onClick={() => setFieldsDraft(prev => [...prev, { name: "", description: "", example: "" }])}
                        className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-violet-600 text-white hover:bg-violet-700"
                      >
                        + Add Field
                      </button>
                    </div>
                  </div>

                  {fieldsDraft.length === 0 ? (
                    <p className="text-xs text-gray-400 italic text-center py-4">No fields yet. Click "+ Add Field" or go back and analyze a sample document.</p>
                  ) : (
                    <div className="space-y-2">
                      <div className="grid grid-cols-[1fr_2fr_1.5fr_auto] gap-2 text-[10px] font-bold text-gray-400 uppercase tracking-wide px-1">
                        <span>Field name</span><span>Description</span><span>Example value</span><span></span>
                      </div>
                      {fieldsDraft.map((f, i) => (
                        <div key={i} className="grid grid-cols-[1fr_2fr_1.5fr_auto] gap-2 items-center bg-gray-50 border border-gray-200 rounded-lg p-2">
                          <input
                            value={f.name}
                            onChange={e => setFieldsDraft(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                            placeholder="field_name"
                            className="text-xs font-mono border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-300"
                          />
                          <input
                            value={f.description}
                            onChange={e => setFieldsDraft(prev => prev.map((x, j) => j === i ? { ...x, description: e.target.value } : x))}
                            placeholder="What this field represents"
                            className="text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-300"
                          />
                          <input
                            value={f.example}
                            onChange={e => setFieldsDraft(prev => prev.map((x, j) => j === i ? { ...x, example: e.target.value } : x))}
                            placeholder={`e.g. "INV-001"`}
                            className="text-xs font-mono border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-200 bg-white"
                          />
                          <button onClick={() => setFieldsDraft(prev => prev.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500 text-base px-1">×</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Classification examples */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-gray-700">
                      Classification Examples <span className="text-gray-400 font-normal">(for <code className="bg-gray-100 px-1 rounded">ai_classify()</code>)</span>
                    </p>
                    <button
                      onClick={generateExamples}
                      disabled={examplesLoading}
                      className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                    >
                      {examplesLoading ? "⏳ Generating…" : "✨ Auto-generate"}
                    </button>
                  </div>
                  <p className="text-[10px] text-gray-400">Up to 3 example sentences describing what this document type looks like. Helps the classifier on edge cases.</p>
                  <div className="space-y-1.5">
                    {[0, 1, 2].map(idx => (
                      <div key={idx} className="flex gap-2">
                        <span className="text-[10px] text-gray-400 w-4 flex-shrink-0 mt-2">{idx + 1}.</span>
                        <input
                          value={classExamples[idx] ?? ""}
                          onChange={e => setClassExamples(prev => { const n = [...prev]; n[idx] = e.target.value; return n; })}
                          placeholder={`Example ${idx + 1}: "This document is a ${dtLabel} containing…"`}
                          className="flex-1 text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-300"
                        />
                      </div>
                    ))}
                  </div>
                </div>

                {/* Parse instructions */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-gray-700">
                      Parse Instructions <span className="text-gray-400 font-normal">(for <code className="bg-gray-100 px-1 rounded">ai_parse_document()</code>)</span>
                    </p>
                    <div className="flex items-center gap-2">
                      <button onClick={() => setShowParseEditor(v => !v)} className="text-xs text-gray-500 hover:text-gray-800">
                        {showParseEditor ? "▲ Hide" : "▼ Show editor"}
                      </button>
                      <button
                        onClick={generateHints}
                        disabled={hintsLoading}
                        className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                      >
                        {hintsLoading ? "⏳ Generating…" : "💡 Generate Hints"}
                      </button>
                    </div>
                  </div>

                  {showParseEditor && (
                    <>
                      <div className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-3 text-xs text-amber-800">
                        <p className="font-bold mb-1">💡 Effective parse instruction patterns:</p>
                        <ul className="list-disc ml-4 space-y-0.5 text-amber-700">
                          <li>Field aliases: <code className="bg-amber-100 px-0.5 rounded">&quot;vendor_id may also appear as Supplier Code or Partner No&quot;</code></li>
                          <li>Date normalization: <code className="bg-amber-100 px-0.5 rounded">&quot;Normalize all dates to YYYY-MM-DD&quot;</code></li>
                          <li>Array fields: <code className="bg-amber-100 px-0.5 rounded">&quot;line_items is an array — capture all rows including subtotals&quot;</code></li>
                          <li>Missing values: <code className="bg-amber-100 px-0.5 rounded">&quot;Return null, not empty string, for genuinely absent fields&quot;</code></li>
                          <li>Layout hints: <code className="bg-amber-100 px-0.5 rounded">&quot;Total amount is in the bottom-right table cell&quot;</code></li>
                        </ul>
                      </div>
                      <textarea
                        value={parseInstrDraft}
                        onChange={e => setParseInstrDraft(e.target.value)}
                        rows={8}
                        placeholder={`# Parse Instructions for ${dtLabel}\n\nGoal: Extract structured data from ${dtLabel} documents.\n\n- Extract all key identifiers as exact strings\n- Normalize dates to YYYY-MM-DD\n- Return null for absent fields\n- Monetary values: extract numeric amount only`}
                        className="w-full text-xs font-mono border border-gray-300 rounded-xl px-4 py-3 resize-y focus:outline-none focus:ring-2 focus:ring-emerald-400"
                        spellCheck={false}
                      />
                    </>
                  )}
                  {!showParseEditor && (
                    <p className="text-[10px] text-gray-400 italic">
                      {parseInstrDraft ? `${parseInstrDraft.length} chars — click "Show editor" to edit` : 'Click "Generate Hints" to create instructions automatically, or "Show editor" to write manually.'}
                    </p>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center justify-between pt-4 border-t border-gray-100">
                  <button onClick={() => setWStep("s2_source")} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => commitDocType(false)}
                      className="px-4 py-2.5 text-sm font-semibold rounded-xl border border-gray-300 text-gray-700 hover:bg-gray-50"
                    >
                      ✅ Save & Add Another Type
                    </button>
                    <button
                      onClick={() => commitDocType(true)}
                      disabled={saving || fieldsDraft.length === 0}
                      className="px-6 py-2.5 text-sm font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
                    >
                      {saving ? "Saving…" : "✅ Proceed to Process Documents →"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Cancel wizard link */}
            <p className="text-xs text-center text-gray-400">
              <button onClick={() => setWStep("list")} className="hover:text-gray-700 underline">
                ← Back to Doc Types List
              </button>
            </p>
          </div>
        )}

      </div>
    </div>
  );
}
// ────────────────────────────────────────────────────────────────────────────
// ProcessDocuments — Configure → Preview → Run
// ────────────────────────────────────────────────────────────────────────────

type ProcStep = "configure" | "preview" | "run";
type ProcMode = "interactive" | "batch";

type DocTypeSchema = {
    doc_type: string;
    display_name?: string;
    volume_path?: string;
    extraction_schema?: string;
};

type ProcessingLog = {
    stats: {
        total_files?: number;
        success_count?: number;
        failed_count?: number;
        skipped_count?: number;
        last_processed_at?: string;
    };
    by_doc_type: { doc_type: string; count: number; success: number; failed: number }[];
    recent: { file_name: string; doc_type: string; status: string; processed_at: string; records_written?: number; error_message?: string; job_run_id?: number }[];
};

type PreviewRow = Record<string, string | null>;

function ProcessStepBar({ step, onStep }: { step: ProcStep; onStep: (s: ProcStep) => void }) {
    const steps: { id: ProcStep; label: string }[] = [
        { id: "configure", label: "1. Configure" },
        { id: "preview",   label: "2. Preview" },
        { id: "run",       label: "3. Run" },
    ];
    return (
        <div className="flex items-center gap-0 bg-white border border-gray-200 rounded-xl overflow-hidden mb-5">
            {steps.map((s) => {
                const active = s.id === step;
                    return (
                        <button
                            key={s.id}
                            onClick={() => onStep(s.id)}
                            className={`flex-1 py-2.5 text-xs font-semibold transition-colors border-r last:border-0 border-gray-100
                                ${active ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-50 cursor-pointer"}`}
                        >
                            {s.label}
                        </button>
                    );
            })}
        </div>
    );
}

// ── Pipeline stage definitions ────────────────────────────────────────────────
const PIPELINE_STAGES = [
    { id: "prepare",   label: "Prepare Pipeline",          desc: "Dedup check, table setup, parameter validation",     icon: "⚙️",  est_ms: 30_000  },
    { id: "parse",     label: "Parse Documents (AI)",      desc: "ai_parse_document — convert files to text & VARIANT",icon: "📄",  est_ms: 120_000 },
    { id: "extract",   label: "Extract Document Content",  desc: "Read parsed output, join content tables",            icon: "📝",  est_ms: 60_000  },
    { id: "classify",  label: "Classify & Extract Fields", desc: "ai_classify + ai_extract per document type",         icon: "🏷️", est_ms: 180_000 },
    { id: "graph",     label: "Build Knowledge Graph",     desc: "Persist gold tables, extracted_fields, entities",    icon: "🕸️",  est_ms: 60_000  },
    { id: "index",     label: "Index for Semantic Search", desc: "ai_prep_search → document_chunks for vector search", icon: "🔍",  est_ms: 90_000  },
    { id: "agent",     label: "Register AI Agent",         desc: "Log model in MLflow, register in Unity Catalog",     icon: "🤖",  est_ms: 30_000  },
];

const TOTAL_STAGE_MS = PIPELINE_STAGES.reduce((s, p) => s + p.est_ms, 0);

// Map Databricks task_key values to PIPELINE_STAGES ids
const TASK_STAGE_MAP: Record<string, string> = {
    task_prepare: "prepare", prepare: "prepare",
    task_parse:   "parse",   parse:   "parse",
    task_extract: "extract", extract: "extract",
    task_classify:"classify",classify:"classify",
    task_graph:   "graph",   graph:   "graph",
    task_index:   "index",   index:   "index",   vector_search: "index",
    task_agent:   "agent",   agent:   "agent",
};

type StageStatus = "pending" | "running" | "done" | "failed";

function PipelineStagesDisplay({
    pipelineStatus,
    startTimeMs,
    elapsedMs,
    tasks,
    runMeta,
}: {
    pipelineStatus: string | null | undefined;
    startTimeMs?: number | null;
    elapsedMs?: number | null;
    tasks?: TaskStatus[];
    runMeta?: RunMeta | null;
}) {
    const isRunning  = pipelineStatus === "running";
    const isSuccess  = pipelineStatus === "succeeded";
    const isFailed   = pipelineStatus === "failed";

    // Live ticker — updates every 5s while running so the active stage advances
    const [_tick, setTick] = useState(0);
    useEffect(() => {
        if (!isRunning) return;
        const id = setInterval(() => setTick(v => v + 1), 5000);
        return () => clearInterval(id);
    }, [isRunning]);

    // Build a task-key → status map from real Databricks data, sorted by PIPELINE_STAGES order
    const taskMap = new Map<string, TaskStatus>();
    if (tasks && tasks.length > 0) {
        for (const t of tasks) {
            const stageId = TASK_STAGE_MAP[t.task_key.toLowerCase()] ?? t.task_key.toLowerCase();
            taskMap.set(stageId, t);
        }
    }
    const hasRealTasks = taskMap.size > 0;

    // Compute which stage is active based on live elapsed time (fallback when no real tasks yet)
    const liveElapsed = isRunning && startTimeMs
        ? Math.max(0, Date.now() - startTimeMs)
        : (elapsedMs ?? null);

    let activeIdxFallback = -1;
    if (!hasRealTasks && (isRunning || isFailed) && liveElapsed != null && liveElapsed >= 0) {
        let cum = 0;
        for (let i = 0; i < PIPELINE_STAGES.length; i++) {
            cum += PIPELINE_STAGES[i].est_ms;
            if (liveElapsed < cum) { activeIdxFallback = i; break; }
        }
        if (activeIdxFallback === -1) activeIdxFallback = PIPELINE_STAGES.length - 1;
    }

    function stageStatus(idx: number): StageStatus {
        const stageId = PIPELINE_STAGES[idx].id;

        // Use real Databricks task status when available
        if (hasRealTasks) {
            const t = taskMap.get(stageId);
            if (!t) {
                // Task not yet reported — treat as pending while running, done if overall succeeded
                return isSuccess ? "done" : "pending";
            }
            const s = t.status.toLowerCase();
            if (s === "succeeded" || s === "success") return "done";
            if (s === "running")  return "running";
            if (s === "failed")   return "failed";
            if (s === "skipped")  return "done";
            return "pending";
        }

        // Fallback: time-based simulation
        if (isSuccess)                  return "done";
        if (!isRunning && !isFailed)    return "pending";
        if (isRunning) {
            if (idx < activeIdxFallback)  return "done";
            if (idx === activeIdxFallback) return "running";
            return "pending";
        }
        if (idx < activeIdxFallback)  return "done";
        if (idx === activeIdxFallback) return "failed";
        return "pending";
    }

    function stageDuration(idx: number): number | null {
        if (!hasRealTasks) return null;
        const t = taskMap.get(PIPELINE_STAGES[idx].id);
        return t?.duration_ms ?? null;
    }

    return (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-sm font-bold text-gray-800">Pipeline Progress</h3>
                <div className="flex items-center gap-3">
                    {isRunning && (
                        <span className="text-xs text-blue-600 animate-pulse font-medium flex items-center gap-1">
                            <span className="inline-block animate-spin">⟳</span>
                            {hasRealTasks ? "Live" : "Running — refreshes in 60s"}
                        </span>
                    )}
                    {isSuccess && <span className="text-xs text-green-600 font-semibold">✓ Completed</span>}
                    {isFailed  && <span className="text-xs text-red-600 font-semibold">✗ Failed</span>}
                    {!isRunning && !isSuccess && !isFailed && (
                        <span className="text-xs text-gray-400">Not started</span>
                    )}
                    {elapsedMs != null && !isRunning && (
                        <span className="text-[11px] text-gray-400 font-mono">{fmtDur(elapsedMs)}</span>
                    )}
                </div>
            </div>
            <div className="divide-y divide-gray-50">
                {PIPELINE_STAGES.map((stage, idx) => {
                    const st = stageStatus(idx);
                    const dur = stageDuration(idx);
                    return (
                        <div key={stage.id}
                            className={`flex items-center gap-4 px-5 py-3 transition-colors
                                ${st === "running" ? "bg-blue-50" :
                                  st === "done"    ? "bg-green-50/40" :
                                  st === "failed"  ? "bg-red-50" : ""}`}>
                            {/* Stage number / status icon */}
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0 font-bold
                                ${st === "done"    ? "bg-green-100 text-green-600" :
                                  st === "running" ? "bg-blue-100 text-blue-600 animate-pulse" :
                                  st === "failed"  ? "bg-red-100 text-red-600" :
                                  "bg-gray-100 text-gray-400"}`}>
                                {st === "done"    ? "✓" :
                                 st === "running" ? <span className="animate-spin inline-block text-xs">⟳</span> :
                                 st === "failed"  ? "✗" :
                                 String(idx + 1)}
                            </div>

                            {/* Stage icon */}
                            <span className={`text-lg shrink-0 ${st === "pending" ? "opacity-30" : ""}`}>
                                {stage.icon}
                            </span>

                            {/* Label + desc */}
                            <div className="flex-1 min-w-0">
                                <p className={`text-sm font-semibold leading-tight
                                    ${st === "done"    ? "text-green-800" :
                                      st === "running" ? "text-blue-800" :
                                      st === "failed"  ? "text-red-800" :
                                      "text-gray-400"}`}>
                                    {stage.label}
                                </p>
                                <p className={`text-[11px] leading-snug mt-0.5
                                    ${st === "pending" ? "text-gray-300" : "text-gray-400"}`}>
                                    {stage.desc}
                                </p>
                            </div>

                            {/* Status badge / timing */}
                            <div className="shrink-0 text-right">
                                {st === "done" && (
                                    <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold">
                                        {dur != null ? fmtDur(dur) : "done"}
                                    </span>
                                )}
                                {st === "running" && (
                                    <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-semibold animate-pulse">
                                        {hasRealTasks ? "running…" : `~${Math.round(stage.est_ms / 60000)}m`}
                                    </span>
                                )}
                                {st === "pending" && (
                                    <span className="text-[10px] text-gray-300">
                                        ~{Math.round(stage.est_ms / 60000)}m
                                    </span>
                                )}
                                {st === "failed" && (
                                    <span className="text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">failed</span>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
            {/* Footer: estimated total + job metadata */}
            <div className="border-t border-gray-100">
                <div className="px-5 py-2.5 bg-gray-50 flex items-center justify-between">
                    <span className="text-[11px] text-gray-400">Total estimated duration</span>
                    <span className="text-[11px] font-semibold text-gray-600">
                        ~{Math.round(TOTAL_STAGE_MS / 60000)} minutes
                    </span>
                </div>
                {runMeta && (
                    <div className="px-5 py-2.5 bg-blue-50 border-t border-blue-100 flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-4 text-[11px] text-gray-500">
                            {runMeta.job_name && (
                                <span>Job: <span className="font-mono text-gray-700">{runMeta.job_name}</span></span>
                            )}
                            {runMeta.run_id && (
                                <span>Run: <span className="font-mono text-gray-700">#{runMeta.run_id}</span></span>
                            )}
                            {runMeta.triggered_at && (
                                <span className="text-gray-400">{runMeta.triggered_at}</span>
                            )}
                        </div>
                        {runMeta.run_url && (
                            <a href={runMeta.run_url} target="_blank" rel="noreferrer"
                               className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 flex items-center gap-0.5">
                                Open in Databricks →
                            </a>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}


function ProcessDocuments({ domainId, onRunComplete }: { domainId: string; onRunComplete: () => void }) {
    const [showGuide, setShowGuide]     = useState(false);
    const [step, setStep]               = useState<ProcStep>("configure");
    const [docTypeSchemas, setDocTypeSchemas] = useState<DocTypeSchema[]>([]);
    const [selectedTypes, setSelectedTypes]   = useState<string[]>([]);
    const [skipNoSchema, setSkipNoSchema]     = useState(true);
    const [volumePath, setVolumePath]         = useState("");
    const [jobName, setJobName]               = useState("");
    const [schedCron, setSchedCron]           = useState("");
    const [schedPreset, setSchedPreset]       = useState("");
    const [useNotifications, setUseNotifications] = useState(false);
    const [applyingSchedule, setApplyingSchedule] = useState(false);
    const [scheduleApplied, setScheduleApplied]   = useState(false);
    const [scheduleError, setScheduleError]       = useState("");
    const [currentJobCron, setCurrentJobCron]     = useState<string|null>(null);
    const [mode, setMode]                     = useState<ProcMode>("batch");
    const [batchSize, setBatchSize]           = useState(5);
    const [configLoading, setConfigLoading]   = useState(true);
    const [savingConfig, setSavingConfig]     = useState(false);
    const [configSaved, setConfigSaved]       = useState(false);
    const [configLastSaved, setConfigLastSaved] = useState<string | null>(null);

    // Volume dropdown
    interface AvailVol { catalog: string; schema: string; name: string; full_path: string; label: string; }
    const [availVols, setAvailVols]           = useState<AvailVol[]>([]);
    const [volsLoading, setVolsLoading]       = useState(false);
    const [volsLoaded, setVolsLoaded]         = useState(false);

    async function loadAvailVols() {
        if (volsLoaded) return;
        setVolsLoading(true);
        try {
            const r = await fetch("/api/docintel/list-volumes");
            if (r.ok) {
                const d = await r.json();
                setAvailVols(d.volumes || []);
                setVolsLoaded(true);
            }
        } catch { /* silent */ }
        setVolsLoading(false);
    }

    // Preview
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewRows, setPreviewRows]       = useState<PreviewRow[]>([]);
    const [previewDocType, setPreviewDocType] = useState("");
    const [previewFile, setPreviewFile]       = useState("");
    const [previewError, setPreviewError]     = useState("");

    // Run
    const [pipelineData, setPipelineData]     = useState<PipelineData | null>(null);
    const [triggering, setTriggering]         = useState(false);
    const [runMeta, setRunMeta]               = useState<RunMeta | null>(null);
    const [procLog, setProcLog]               = useState<ProcessingLog | null>(null);
    const [logLoading, setLogLoading]         = useState(false);
    const [showLog, setShowLog]               = useState(false);
    // True only after the user clicks the Run button in THIS session.
    // Prevents the progress bar from appearing on-mount from a previous run's cached status.
    const [sessionRunTriggered, setSessionRunTriggered] = useState(false);
    const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null);
    const idleRef    = useRef<ReturnType<typeof setInterval> | null>(null);
    const prevStatus = useRef<string | null>(null);

    // Clean state
    const [cleanConfirm, setCleanConfirm]   = useState(false);
    const [cleaning, setCleaning]           = useState(false);
    const [cleanResult, setCleanResult]     = useState<{ status: string; deleted: string[]; errors: string[]; job_runs_deleted: number } | null>(null);

    // ── Load configured doc type schemas ────────────────────────────────────
    useEffect(() => {
        (async () => {
            setConfigLoading(true);
            try {
                const r = await fetch("/api/docintel/doc-type-schemas");
                if (r.ok) {
                    const d = await r.json();
                    const schemas: DocTypeSchema[] = d.schemas || [];
                    setDocTypeSchemas(schemas);
                    setSelectedTypes(schemas.map(s => s.doc_type));
                }
            } catch { /* silent */ }

            // Load saved processing config for this domain
            try {
                const r2 = await fetch(`/api/docintel/processing-config?domain_id=${encodeURIComponent(domainId)}`);
                if (r2.ok) {
                    const cfg = await r2.json();
                    if (cfg.found) {
                        if (cfg.volume_path) setVolumePath(cfg.volume_path);
                        if (cfg.doc_types) {
                            try { setSelectedTypes(JSON.parse(cfg.doc_types)); } catch { /* ignore */ }
                        }
                        if (cfg.job_name) setJobName(cfg.job_name);
                        if (cfg.schedule_cron) {
                            setSchedCron(cfg.schedule_cron);
                            const known: Record<string, string> = {
                                "0 2 * * *": "daily_2am", "0 0 * * *": "daily_midnight",
                                "0 6 * * 1": "weekly_mon",
                            };
                            setSchedPreset(known[cfg.schedule_cron] || "custom");
                        }
                        if (cfg.skip_no_schema !== undefined) setSkipNoSchema(!!cfg.skip_no_schema);
                        if (cfg.updated_at) setConfigLastSaved(cfg.updated_at);
                    }
                }
            } catch { /* silent */ }

            // Load current job schedule from Jobs API
            try {
                const r3 = await fetch(`/api/docintel/job-schedule?domain_id=${encodeURIComponent(domainId)}`);
                if (r3.ok) {
                    const js = await r3.json();
                    setCurrentJobCron(js.cron_expression || null);
                    if (js.use_notifications !== undefined) setUseNotifications(!!js.use_notifications);
                    // Pre-populate schedule fields from actual job if not already set from config
                    if (!schedCron && js.cron_expression) {
                        setSchedCron(js.cron_expression);
                        const known: Record<string, string> = {
                            "0 2 * * *": "daily_2am", "0 0 * * *": "daily_midnight",
                            "0 6 * * 1": "weekly_mon", "0 * * * *": "hourly",
                        };
                        setSchedPreset(known[js.cron_expression] || "custom");
                    }
                }
            } catch { /* silent */ }

            setConfigLoading(false);
        })();
    }, [domainId]);

    // ── Pipeline status polling ──────────────────────────────────────────────
    const fetchPipelineStatus = useCallback(async () => {
        try {
            const r = await fetch(`/api/docintel/pipeline-status?domain_id=${encodeURIComponent(domainId)}`);
            if (!r.ok) return;
            const d: PipelineData = await r.json();
            setPipelineData(d);
            if (d.status === "running") {
                if (!pollRef.current) pollRef.current = setInterval(fetchPipelineStatus, 60000);
                if (idleRef.current) { clearInterval(idleRef.current); idleRef.current = null; }
            } else {
                if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                if (!idleRef.current) idleRef.current = setInterval(fetchPipelineStatus, 5 * 60 * 1000);
                if (prevStatus.current === "running") {
                    onRunComplete();
                    // Auto-open log and refresh it when a run finishes
                    setProcLog(null);          // clear stale data so fresh fetch is triggered
                    setShowLog(true);          // open the log panel automatically
                    fetchProcessingLog();
                }
            }
            prevStatus.current = d.status;
        } catch { /* silent */ }
    }, [domainId, onRunComplete]);

    useEffect(() => {
        fetchPipelineStatus();
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
            if (idleRef.current) clearInterval(idleRef.current);
        };
    }, [fetchPipelineStatus]);

    // ── Save config ──────────────────────────────────────────────────────────
    async function saveConfig() {
        setSavingConfig(true);
        try {
            const body = {
                domain_id: domainId,
                volume_path: volumePath,
                doc_types: JSON.stringify(selectedTypes),
                job_name: jobName,
                schedule_cron: schedCron,
                skip_no_schema: skipNoSchema,
            };
            const r = await fetch("/api/docintel/processing-config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (r.ok) { setConfigSaved(true); setConfigLastSaved(new Date().toISOString()); setTimeout(() => setConfigSaved(false), 3000); }
        } catch { /* silent */ }
        setSavingConfig(false);
    }

    // ── Apply schedule to Databricks job ────────────────────────────────────
    async function applyScheduleToJob() {
        setApplyingSchedule(true);
        setScheduleError("");
        try {
            const r = await fetch("/api/docintel/job-schedule", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    domain_id:         domainId,
                    cron_expression:   schedCron || null,
                    timezone_id:       "UTC",
                    use_notifications: useNotifications,
                }),
            });
            const d = await r.json();
            if (!r.ok) { setScheduleError(d.detail || "Failed to update schedule"); }
            else {
                setCurrentJobCron(d.cron_expression || null);
                setScheduleApplied(true);
                setTimeout(() => setScheduleApplied(false), 4000);
            }
        } catch (e: unknown) {
            setScheduleError(e instanceof Error ? e.message : String(e));
        }
        setApplyingSchedule(false);
    }

    // ── Clean processing state ───────────────────────────────────────────────
    async function doClean() {
        setCleaning(true);
        setCleanResult(null);
        try {
            const r = await fetch(
                `/api/docintel/clean-processing-state?domain_id=${encodeURIComponent(domainId)}&delete_job_runs=true`,
                { method: "POST" }
            );
            const d = await r.json();
            setCleanResult(d);
            // Reset UI state to reflect empty data
            setPipelineData(null);
            setProcLog(null);
        } catch (e: any) {
            setCleanResult({ status: "error", deleted: [], errors: [String(e)], job_runs_deleted: 0 });
        }
        setCleaning(false);
        setCleanConfirm(false);
    }

    // ── Preset schedule handler ──────────────────────────────────────────────
    function applyPreset(p: string) {
        setSchedPreset(p);
        const map: Record<string, string> = {
            daily_2am: "0 2 * * *",
            daily_midnight: "0 0 * * *",
            weekly_mon: "0 6 * * 1",
            hourly: "0 * * * *",
            custom: schedCron,
        };
        setSchedCron(map[p] ?? "");
    }

    // ── Preview sample file ──────────────────────────────────────────────────
    async function runPreview() {
        if (!volumePath || selectedTypes.length === 0) {
            setPreviewError("Set a volume path and select at least one doc type first.");
            return;
        }
        setPreviewLoading(true);
        setPreviewError("");
        setPreviewRows([]);
        try {
            // List files in volume, pick first
            const r1 = await fetch(`/api/docintel/volume-files?volume_path=${encodeURIComponent(volumePath)}&limit=3`);
            if (!r1.ok) throw new Error(await r1.text());
            const d1 = await r1.json();
            const files: { path: string; name: string }[] = d1.files || [];
            if (!files.length) throw new Error("No files found in the volume.");

            const f = files[0];
            setPreviewFile(f.name);

            // Build full path — some volume-files responses already include the full path
            const filePath = f.path
                ? f.path
                : `${volumePath.replace(/\/$/, "")}/${f.name}`;

            // Run schema-preview analysis
            const r2 = await fetch("/api/docintel/domain-schema-preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    domain_id: domainId,
                    file_path: filePath,
                    doc_types: selectedTypes,
                }),
            });
            if (!r2.ok) throw new Error(await r2.text());
            const d2 = await r2.json();
            setPreviewDocType(d2.predicted_doc_type || d2.doc_type || "unknown");
            // Backend returns `extracted_fields` as a flat object; wrap in array for the table
            let rows: PreviewRow[] = [];
            if (d2.preview_rows && Array.isArray(d2.preview_rows) && d2.preview_rows.length) {
                rows = d2.preview_rows;
            } else if (d2.extracted_fields && typeof d2.extracted_fields === "object") {
                // Convert {field: value} → [{field: value}] for table display
                const cleaned: PreviewRow = {};
                for (const [k, v] of Object.entries(d2.extracted_fields)) {
                    if (v != null && v !== "") cleaned[k] = String(v);
                }
                if (Object.keys(cleaned).length > 0) rows = [cleaned];
            }
            if (rows.length === 0 && d2.error) throw new Error(d2.error);
            if (rows.length === 0) throw new Error("Analysis returned no extracted fields. Check that your doc type schema has extraction fields configured.");
            setPreviewRows(rows);
        } catch (e: unknown) {
            setPreviewError(String(e));
        }
        setPreviewLoading(false);
    }

    // ── Trigger pipeline ─────────────────────────────────────────────────────
    async function doTrigger() {
        setTriggering(true);
        setSessionRunTriggered(true);   // user explicitly started this run
        try {
            const params = new URLSearchParams({ domain_id: domainId });
            if (volumePath) params.set("volume_path", volumePath);
            if (selectedTypes.length) params.set("doc_types", JSON.stringify(selectedTypes));
            params.set("mode", mode);
            params.set("batch_size", mode === "interactive" ? String(batchSize) : "999");
            params.set("skip_no_schema", String(skipNoSchema));
            if (jobName) params.set("job_name", jobName);
            if (schedCron && mode === "batch") params.set("schedule_cron", schedCron);

            const r = await fetch(`/api/docintel/trigger-pipeline?${params.toString()}`, { method: "POST" });
            const resp = r.ok ? await r.json() : null;
            if (resp?.success) {
                const meta: RunMeta = {
                    run_id:       resp.run_id,
                    run_url:      resp.run_url,
                    job_id:       resp.job_id,
                    job_name:     resp.job_name,
                    triggered_at: new Date().toLocaleString("en-US", {
                        month: "short", day: "numeric",
                        hour: "2-digit", minute: "2-digit", second: "2-digit",
                    }),
                };
                setRunMeta(meta);
                setPipelineData(prev => prev ? { ...prev, status: "running", tasks: [] } : { status: "running" });
                prevStatus.current = "running";
                if (idleRef.current) { clearInterval(idleRef.current); idleRef.current = null; }
                // Faster polling for interactive (user watching live), slower for batch
                const pollMs = mode === "interactive" ? 10_000 : 30_000;
                if (!pollRef.current) pollRef.current = setInterval(fetchPipelineStatus, pollMs);
            } else {
                const errText = !r.ok ? await r.text() : "Unknown error";
                setPipelineData(prev => prev ? { ...prev, status: "error", message: errText } : { status: "error", message: errText });
            }
        } catch (e: unknown) {
            setPipelineData(prev => ({ ...(prev ?? { status: "error" }), status: "error", message: String(e) }));
        }
        setTriggering(false);
    }

    // ── Processing log ───────────────────────────────────────────────────────
    async function fetchProcessingLog() {
        setLogLoading(true);
        try {
            const r = await fetch(`/api/docintel/processing-log?domain_id=${encodeURIComponent(domainId)}&limit=50`);
            if (r.ok) { const d = await r.json(); setProcLog(d); }
        } catch { /* silent */ }
        setLogLoading(false);
    }

    useEffect(() => {
        if (showLog && !procLog) fetchProcessingLog(); // eslint-disable-line react-hooks/exhaustive-deps
    }, [showLog]); // intentionally only re-runs on showLog toggle

    const isRunning  = pipelineData?.status === "running";
    const newDocs    = pipelineData?.new_docs_count ?? 0;
    // output table names for summary display
    const _outputTables = [`${domainId}.parsed_documents`, `${domainId}.extracted_fields`, `${domainId}.document_chunks`, "platform.file_processing_log"];
    void _outputTables; // used for reference

    if (configLoading) {
        return <div className="p-8 text-center text-sm text-gray-400">Loading configuration…</div>;
    }

    return (
        <div className="max-w-4xl mx-auto p-4 space-y-4">

            <ProcessStepBar step={step} onStep={setStep} />

            {/* ─── Getting Started Guide ──────────────────────────────────── */}
            <div className="rounded-xl border border-blue-100 bg-blue-50 overflow-hidden">
                <button
                    type="button"
                    onClick={() => setShowGuide(v => !v)}
                    className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-blue-800 hover:bg-blue-100/60 transition-colors cursor-pointer"
                >
                    <span className="flex items-center gap-2">📖 Getting Started Guide — How to set up and run document processing</span>
                    <span className="text-blue-500 text-base">{showGuide ? "▲" : "▼"}</span>
                </button>

                {showGuide && (
                    <div className="px-5 pb-5 space-y-5 border-t border-blue-100 pt-4 text-xs text-gray-700">

                        {/* Overview */}
                        <div>
                            <p className="font-bold text-sm text-blue-900 mb-1">Overview</p>
                            <p className="leading-relaxed text-gray-600">
                                Document processing runs in three steps: <strong>Configure</strong> (set volume, doc types, schedule),
                                <strong> Preview</strong> (test extraction on a sample file), and <strong>Run</strong> (trigger interactive or batch pipeline).
                                The pipeline is fully generic — it works for any subject area and any document type you have configured.
                            </p>
                        </div>

                        {/* Pre-req */}
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                            <p className="font-bold text-amber-800 mb-1">⚠️ Pre-requisite: Schema Setup</p>
                            <p className="text-amber-700 leading-relaxed">
                                Before processing documents, configure at least one document type schema in the <strong>Schema Setup</strong> tab.
                                Each schema tells the AI what fields to extract for that document type.
                                24 pre-built schemas are available in the global library (health inspections, contracts, permits, COAs, etc.) —
                                select one and save it to your subject area, or create a custom schema from a sample file.
                            </p>
                            <p className="text-amber-600 mt-1">
                                <strong>Tip:</strong> You can still process documents without a schema — they will be parsed and search-indexed
                                but extraction fields will be empty. Uncheck "skip files with no schema" below to enable this.
                            </p>
                        </div>

                        {/* Step 1 */}
                        <div>
                            <p className="font-bold text-blue-800 mb-2">Step 1 — Configure</p>
                            <div className="space-y-2 pl-2 border-l-2 border-blue-200">
                                <div>
                                    <span className="font-semibold text-gray-800">📂 Source Volume:</span>
                                    <span className="text-gray-600"> Select the Unity Catalog volume where your documents are stored (e.g.
                                    <code className="bg-gray-100 px-1 mx-1 rounded">/Volumes/jai_docintel/compliance/documents</code>).
                                    Use the dropdown to browse available volumes or type the path directly.</span>
                                </div>
                                <div>
                                    <span className="font-semibold text-gray-800">📋 Document Types:</span>
                                    <span className="text-gray-600"> Select which document types to process. Only documents matching these types will have
                                    structured fields extracted. Use <em>Select All</em> to include everything, or cherry-pick specific types.</span>
                                </div>
                                <div>
                                    <span className="font-semibold text-gray-800">⚙️ Job Name:</span>
                                    <span className="text-gray-600"> Leave blank to use the existing Databricks job for this subject area.
                                    Provide a name only if you want to create or target a specific job.</span>
                                </div>
                                <div>
                                    <span className="font-semibold text-gray-800">🗓 Batch Schedule:</span>
                                    <span className="text-gray-600"> Choose a preset (Daily 2 AM, Weekly, Hourly) or enter a custom cron expression.
                                    Click <em>Apply Schedule to Job</em> to update the Databricks job trigger.
                                    Auto Loader runs incrementally — only new files since the last run are processed.</span>
                                </div>
                            </div>
                        </div>

                        {/* Step 2 */}
                        <div>
                            <p className="font-bold text-blue-800 mb-2">Step 2 — Preview</p>
                            <p className="text-gray-600 leading-relaxed">
                                Preview tests extraction on a single sample file from your volume before committing to a full run.
                                Select a doc type, click <em>Run Preview</em>, and the system will pick a file, classify it, and show the
                                extracted fields — confirming your schema is set up correctly.
                                Always run a preview after setting up a new schema.
                            </p>
                        </div>

                        {/* Step 3 */}
                        <div>
                            <p className="font-bold text-blue-800 mb-2">Step 3 — Run</p>
                            <div className="space-y-2 pl-2 border-l-2 border-blue-200">
                                <div>
                                    <span className="font-semibold text-gray-800">⚡ Interactive Mode:</span>
                                    <span className="text-gray-600"> Processes a small batch immediately — great for testing or processing new documents on-demand.
                                    Set the number of files (default 5; enter 999 for all). Results appear in the pipeline progress bar in real time.
                                    Interactive runs re-read all files in the volume (ignores the Auto Loader checkpoint).</span>
                                </div>
                                <div>
                                    <span className="font-semibold text-gray-800">🔄 Batch Mode:</span>
                                    <span className="text-gray-600"> Runs the full pipeline job for this subject area. Uses Auto Loader with file-notification or
                                    directory-listing mode to detect and process only new files since the last run.
                                    Runs according to the schedule set in Configure, or manually triggered here.
                                    Deduplication is automatic — files already in the processing log are skipped.</span>
                                </div>
                            </div>
                        </div>

                        {/* Pipeline steps */}
                        <div>
                            <p className="font-bold text-blue-800 mb-2">Pipeline Steps Explained</p>
                            <div className="grid gap-2">
                                {[
                                    { icon: "⚙️", label: "Prepare Pipeline",         text: "Validates parameters, creates required tables, removes leftover temp tables from prior failed runs, and loads domain config and extraction schemas." },
                                    { icon: "📄", label: "Parse Documents (AI)",      text: "Auto Loader reads new files from your volume. PDFs and images are processed with ai_parse_document (produces a VARIANT). TXT files are read directly and wrapped in a compatible VARIANT. Already-seen files are skipped automatically." },
                                    { icon: "📝", label: "Extract Document Content",  text: "Reads parsed output from the Bronze table (parsed_documents_raw). De-duplicates, applies volume filter, and joins raw text content for classification." },
                                    { icon: "🏷️", label: "Classify & Extract Fields","text": "ai_classify assigns a document type label to each document. For documents matching a configured schema, ai_extract pulls structured fields (e.g. violation_code, deadline, supplier_name). Documents without a schema go through universal schema discovery." },
                                    { icon: "🕸️", label: "Build Knowledge Graph",    text: "Writes classified, extracted documents to parsed_documents (Silver). Persists per-doc-type gold tables (gold_health_inspection_report, gold_permit, etc.) and a unified extracted_fields table for ontology mapping." },
                                    { icon: "🔍", label: "Index for Semantic Search", text: "ai_prep_search chunks each document into context-enriched search passages. Results are written to document_chunks and synced to the Vector Search index for RAG-powered search and the AI Agent." },
                                    { icon: "🤖", label: "Register AI Agent",         text: "Updates the AI agent configuration for this subject area so it can answer questions grounded in the newly processed documents." },
                                ].map(s => (
                                    <div key={s.label} className="flex gap-2 items-start">
                                        <span className="text-base shrink-0 mt-0.5">{s.icon}</span>
                                        <div>
                                            <span className="font-semibold text-gray-800">{s.label}: </span>
                                            <span className="text-gray-600">{s.text}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Output tables */}
                        <div>
                            <p className="font-bold text-blue-800 mb-2">Output Tables</p>
                            <div className="space-y-1.5">
                                {[
                                    { name: `jai_docintel.${domainId}.parsed_documents`,  desc: "All processed documents with doc_type, raw_text, and parsed VARIANT." },
                                    { name: `jai_docintel.${domainId}.extracted_fields`,  desc: "All structured fields extracted per document, in long format (field_name, field_value)." },
                                    { name: `jai_docintel.${domainId}.gold_{doc_type}`,   desc: "Per-doc-type wide tables with each extraction field as a column. Created automatically for each doc type processed." },
                                    { name: `jai_docintel.vectors.document_chunks`,       desc: "ai_prep_search chunks for semantic search. Fed to Vector Search index." },
                                    { name: `jai_docintel.vectors.${domainId}_docs_index`,"desc": "Databricks Vector Search index — powers semantic search and the AI Agent." },
                                    { name: "jai_docintel.platform.file_processing_log",  desc: "Deduplication log. Files already processed (status=success) are never re-processed in batch mode." },
                                    { name: `jai_docintel.${domainId}.suggested_extractions`, desc: "Schema discovery output for documents without a configured schema — review to improve your Schema Setup." },
                                ].map(t => (
                                    <div key={t.name} className="flex items-start gap-2">
                                        <code className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-700 font-mono text-[11px] shrink-0 whitespace-nowrap">{t.name}</code>
                                        <span className="text-gray-500">{t.desc}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* FAQ */}
                        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
                            <p className="font-bold text-gray-800">Common Questions</p>
                            {[
                                { q: "Will already-processed files be re-processed?",  a: "No. Batch mode uses Auto Loader checkpoints + file_processing_log to skip files already processed. Interactive mode intentionally re-reads all files for testing." },
                                { q: "What happens to files with no matching schema?", a: "They are still parsed and search-indexed. ai_extract runs universal schema discovery on them and stores results in suggested_extractions. Turn on 'skip files with no schema' only if you want to exclude them completely." },
                                { q: "Do I need to pre-create gold tables?",           a: "No. The pipeline creates gold_{doc_type} tables automatically the first time a document of that type is processed." },
                                { q: "How does the AI know which file is which doc type?", a: "ai_classify reads the parsed document content and assigns one of your configured labels. The more descriptive your classification examples in Schema Setup, the more accurate the classification." },
                                { q: "How do I add a new document type?",              a: "Go to Schema Setup, enter the document type name, optionally pick from 24 pre-built templates or upload a sample file to auto-generate fields, confirm, and save to your subject area." },
                            ].map(item => (
                                <div key={item.q}>
                                    <p className="font-semibold text-gray-700">Q: {item.q}</p>
                                    <p className="text-gray-500 mt-0.5">A: {item.a}</p>
                                </div>
                            ))}
                        </div>

                    </div>
                )}
            </div>

            {/* ─── STEP 1: Configure ────────────────────────────────────────── */}
            {step === "configure" && (
                <div className="space-y-5">

                    {/* Source volume */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <span className="text-blue-500">📂</span> Source Volume
                        </h3>
                        <p className="text-xs text-gray-500 mb-2">
                            Select a Unity Catalog volume or enter the path manually.
                        </p>

                        {/* Dropdown from available volumes */}
                        <div className="flex gap-2 mb-2">
                            <div className="relative flex-1">
                                <select
                                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 appearance-none pr-8"
                                    value={availVols.find(v => v.full_path === volumePath) ? volumePath : ""}
                                    onChange={e => { if (e.target.value) setVolumePath(e.target.value); }}
                                    onFocus={() => { if (!volsLoaded) loadAvailVols(); }}
                                    onClick={() => { if (!volsLoaded) loadAvailVols(); }}
                                >
                                    <option value="">{volsLoading ? "Loading volumes…" : "— Select a volume —"}</option>
                                    {availVols.map(v => (
                                        <option key={v.full_path} value={v.full_path}>{v.label || v.full_path}</option>
                                    ))}
                                </select>
                                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs">▾</span>
                            </div>
                            <button
                                onClick={loadAvailVols}
                                disabled={volsLoading}
                                className="px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-gray-50 cursor-pointer disabled:opacity-40"
                                title="Refresh volume list"
                            >
                                {volsLoading ? "…" : "↺"}
                            </button>
                        </div>

                        {/* Manual entry */}
                        <input
                            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 font-mono"
                            placeholder="/Volumes/catalog/schema/volume_name"
                            value={volumePath}
                            onChange={e => setVolumePath(e.target.value)}
                        />
                        <p className="text-[11px] text-gray-400 mt-1">
                            You can also type a path directly. Example: <code>/Volumes/jai_docintel/compliance/sample_docs</code>
                        </p>
                    </div>

                    {/* Doc types */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-1 flex items-center gap-2">
                            <span className="text-blue-500">📋</span> Document Types to Process
                        </h3>
                        <p className="text-xs text-gray-500 mb-3">
                            Select which document types to include. Unselected types will be{" "}
                            {skipNoSchema ? "skipped" : "parsed but not extracted"}.
                        </p>
                        {docTypeSchemas.length === 0 ? (
                            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                                No document types configured yet. Go to Schema Setup to define document types first.
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {/* Select All / Deselect All */}
                                <div className="flex items-center justify-between pb-2 border-b border-gray-100">
                                    <span className="text-xs text-gray-500">
                                        {selectedTypes.length} of {docTypeSchemas.length} selected
                                    </span>
                                    <div className="flex gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setSelectedTypes(docTypeSchemas.map(d => d.doc_type))}
                                            disabled={selectedTypes.length === docTypeSchemas.length}
                                            className="text-xs px-2.5 py-1 rounded-md border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
                                        >
                                            Select All
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setSelectedTypes([])}
                                            disabled={selectedTypes.length === 0}
                                            className="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
                                        >
                                            Deselect All
                                        </button>
                                    </div>
                                </div>
                                {docTypeSchemas.map(dt => {
                                    const checked = selectedTypes.includes(dt.doc_type);
                                    return (
                                        <label key={dt.doc_type} className="flex items-center gap-3 cursor-pointer group">
                                            <input
                                                type="checkbox"
                                                checked={checked}
                                                onChange={() =>
                                                    setSelectedTypes(prev =>
                                                        checked
                                                            ? prev.filter(t => t !== dt.doc_type)
                                                            : [...prev, dt.doc_type]
                                                    )
                                                }
                                                className="w-4 h-4 accent-blue-600 cursor-pointer"
                                            />
                                            <div className="flex-1">
                                                <span className="text-sm text-gray-800 font-medium group-hover:text-blue-700">
                                                    {dt.display_name || dt.doc_type}
                                                </span>
                                                {dt.volume_path && (
                                                    <span className="ml-2 text-[10px] text-gray-400">
                                                        vol: {dt.volume_path.split("/").slice(-1)[0]}
                                                    </span>
                                                )}
                                            </div>
                                        </label>
                                    );
                                })}
                                <label className="flex items-center gap-3 cursor-pointer mt-3 pt-3 border-t border-gray-100">
                                    <input
                                        type="checkbox"
                                        checked={!skipNoSchema}
                                        onChange={() => setSkipNoSchema(v => !v)}
                                        className="w-4 h-4 accent-blue-600 cursor-pointer"
                                    />
                                    <span className="text-sm text-gray-600">
                                        Also parse &amp; index files with no matching schema (extraction_data will be null)
                                    </span>
                                </label>
                            </div>
                        )}
                    </div>

                    {/* Pipeline flow explanation */}
                    <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
                        <h3 className="text-xs font-bold text-blue-800 mb-2 uppercase tracking-wide">Processing Pipeline</h3>
                        <div className="flex items-center gap-1.5 flex-wrap text-xs text-blue-700">
                            {["ai_parse_document", "→ ai_classify", "→ ai_extract", "→ ai_prep_search", "→ Delta write", "→ log update"].map(s => (
                                <span key={s} className={`${s.startsWith("→") ? "text-blue-400" : "bg-blue-100 px-2 py-0.5 rounded font-mono"}`}>{s}</span>
                            ))}
                        </div>
                        <p className="text-[11px] text-blue-600 mt-2">
                            Each file is classified first, then the matching extraction schema is applied.
                            Already-processed files are automatically skipped via <code>file_processing_log</code>.
                        </p>
                    </div>

                    {/* Output tables */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <span className="text-blue-500">💾</span> Output Tables
                        </h3>
                        <div className="space-y-1.5">
                            {[
                                { name: "parsed_documents",    desc: "Full parsed text + classification + raw VARIANT" },
                                { name: "extracted_fields",    desc: "All structured fields extracted per doc type" },
                                { name: "document_chunks",     desc: "ai_prep_search chunks for vector search" },
                                { name: "gold_{doc_type}",     desc: "Per-doc-type structured gold tables" },
                                { name: "file_processing_log", desc: "Global processing log for deduplication & reporting (platform schema)" },
                            ].map(t => (
                                <div key={t.name} className="flex items-start gap-2 text-xs">
                                    <code className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-700 font-mono text-[11px] shrink-0">{t.name}</code>
                                    <span className="text-gray-500">{t.desc}</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Job name */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <span className="text-blue-500">⚙️</span> Job Configuration
                        </h3>
                        <div className="space-y-3">
                            <div>
                                <label className="text-xs font-semibold text-gray-600 mb-1 block">Job Name (optional)</label>
                                <input
                                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                                    placeholder={`DocIntel-${domainId}`}
                                    value={jobName}
                                    onChange={e => setJobName(e.target.value)}
                                />
                                <p className="text-[11px] text-gray-400 mt-1">Leave blank to use the existing job for this domain.</p>
                            </div>
                        </div>
                    </div>

                    {/* ── Schedule & Auto Loader ────────────────────────────── */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-sm font-bold text-gray-800">Batch Schedule</h3>
                            {currentJobCron && (
                                <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full font-mono">
                                    Active: {currentJobCron}
                                </span>
                            )}
                            {!currentJobCron && (
                                <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                                    No schedule on job
                                </span>
                            )}
                        </div>

                        {/* Preset buttons */}
                        <div className="grid grid-cols-3 gap-2">
                            {([
                                { id: "daily_2am",      label: "Daily 2 AM UTC",    cron: "0 2 * * *" },
                                { id: "daily_midnight", label: "Daily Midnight UTC", cron: "0 0 * * *" },
                                { id: "weekly_mon",     label: "Weekly Mon 6 AM",   cron: "0 6 * * 1" },
                                { id: "hourly",         label: "Hourly",             cron: "0 * * * *" },
                                { id: "none",           label: "No schedule",        cron: "" },
                                { id: "custom",         label: "Custom cron…",       cron: schedCron },
                            ] as {id:string; label:string; cron:string}[]).map(p => (
                                <button key={p.id}
                                    onClick={() => { setSchedPreset(p.id); setSchedCron(p.cron); }}
                                    className={`text-xs px-2 py-2 rounded-lg border cursor-pointer transition-colors
                                        ${schedPreset === p.id
                                            ? "border-blue-500 bg-blue-50 text-blue-700 font-semibold"
                                            : "border-gray-200 hover:bg-gray-50 text-gray-600"}`}
                                >{p.label}</button>
                            ))}
                        </div>

                        {schedPreset === "custom" && (
                            <input
                                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                                placeholder="e.g. 0 2 * * *  (minute hour dom month dow)"
                                value={schedCron}
                                onChange={e => setSchedCron(e.target.value)}
                            />
                        )}
                        {schedCron && schedPreset !== "custom" && schedPreset !== "none" && (
                            <p className="text-[11px] text-gray-400">Cron: <code className="bg-gray-100 px-1 rounded">{schedCron}</code></p>
                        )}

                        {/* Auto Loader notification mode */}
                        <div className="border-t border-gray-100 pt-3">
                            <label className="flex items-start gap-3 cursor-pointer">
                                <input type="checkbox" checked={useNotifications}
                                    onChange={e => setUseNotifications(e.target.checked)}
                                    className="mt-0.5" />
                                <div>
                                    <p className="text-sm font-medium text-gray-700">Enable File Notification Mode</p>
                                    <p className="text-[11px] text-gray-400 mt-0.5 leading-relaxed">
                                        Auto Loader picks up new files via Azure Event Grid push notifications (sub-minute latency).
                                        Requires Azure Event Grid subscription on the storage account.
                                        Without this, Auto Loader uses directory listing (periodic poll — fine for nightly scheduled jobs).
                                    </p>
                                </div>
                            </label>
                        </div>

                        {/* Apply to job button */}
                        <div className="flex items-center gap-3 border-t border-gray-100 pt-3">
                            <button
                                onClick={applyScheduleToJob}
                                disabled={applyingSchedule}
                                className="text-sm font-semibold px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-40 cursor-pointer flex items-center gap-2"
                            >
                                {applyingSchedule
                                    ? <><span className="animate-spin inline-block">⟳</span> Applying…</>
                                    : scheduleApplied
                                        ? "✓ Applied to Job"
                                        : "Apply Schedule to Job"}
                            </button>
                            <p className="text-[11px] text-gray-400">
                                Updates the Databricks Job trigger and Auto Loader settings immediately.
                            </p>
                        </div>
                        {scheduleError && (
                            <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{scheduleError}</p>
                        )}
                    </div>

                    {/* Save config */}
                    <div className="flex items-center justify-between">
                        <div className="flex flex-col gap-1">
                            <button
                                onClick={saveConfig}
                                disabled={savingConfig}
                                className="text-sm font-semibold px-5 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-40 cursor-pointer"
                            >
                                {savingConfig ? "Saving…" : configSaved ? "✓ Saved" : "Save Configuration"}
                            </button>
                            {configLastSaved && (
                                <span className="text-[11px] text-gray-400">
                                    Last saved {new Date(configLastSaved).toLocaleString()} · {domainId}
                                </span>
                            )}
                        </div>
                        <button
                            onClick={() => { saveConfig(); setStep("preview"); }}
                            className="text-sm font-semibold px-5 py-2 rounded-lg bg-gray-900 text-white hover:bg-gray-700 transition-colors cursor-pointer"
                        >
                            Next: Preview Sample →
                        </button>
                    </div>

                    {/* ── Danger Zone: Clean State ──────────────────────── */}
                    <div className="mt-4 border border-red-200 rounded-xl overflow-hidden">
                        <button
                            onClick={() => { setCleanConfirm(v => !v); setCleanResult(null); }}
                            className="w-full flex items-center justify-between px-5 py-3 text-sm text-red-700 hover:bg-red-50 bg-red-50/40 cursor-pointer"
                        >
                            <span className="font-semibold">🗑 Clean Processing State</span>
                            <span className="text-xs text-red-400">Resets all Library data for this domain → start fresh</span>
                        </button>

                        {cleanConfirm && !cleanResult && (
                            <div className="px-5 py-4 border-t border-red-100 bg-white space-y-3">
                                <p className="text-xs text-gray-700 leading-relaxed">
                                    This will <strong>permanently delete</strong> all processed data for <strong>{domainId}</strong>:
                                </p>
                                <ul className="text-xs text-gray-600 space-y-0.5 list-disc list-inside pl-1">
                                    <li>All rows in <code className="bg-gray-100 px-1 rounded">parsed_documents</code></li>
                                    <li>All rows in <code className="bg-gray-100 px-1 rounded">extracted_fields</code></li>
                                    <li>All rows in <code className="bg-gray-100 px-1 rounded">document_chunks</code></li>
                                    <li>All rows in <code className="bg-gray-100 px-1 rounded">entities</code> and <code className="bg-gray-100 px-1 rounded">relationships</code></li>
                                    <li>Processing log entries for this domain</li>
                                    <li>All previous pipeline job run history</li>
                                </ul>
                                <p className="text-xs text-gray-500 italic">
                                    Schemas, domain config, pipeline config, Copilot prompts, and action log are <strong>not affected</strong>.
                                </p>
                                <div className="flex items-center gap-3 pt-1">
                                    <button
                                        onClick={doClean}
                                        disabled={cleaning}
                                        className="px-4 py-2 text-xs font-bold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 cursor-pointer flex items-center gap-2"
                                    >
                                        {cleaning ? <><span className="animate-spin">⟳</span> Cleaning…</> : "Yes, Delete All Processed Data"}
                                    </button>
                                    <button onClick={() => setCleanConfirm(false)} className="text-xs text-gray-500 hover:text-gray-800 cursor-pointer">Cancel</button>
                                </div>
                            </div>
                        )}

                        {cleanResult && (
                            <div className={`px-5 py-4 border-t text-xs ${cleanResult.status === "ok" ? "bg-green-50 border-green-100" : "bg-amber-50 border-amber-100"}`}>
                                <p className={`font-bold mb-2 ${cleanResult.status === "ok" ? "text-green-700" : "text-amber-700"}`}>
                                    {cleanResult.status === "ok" ? "✓ Clean complete" : "⚠ Partial clean"}
                                    {cleanResult.job_runs_deleted > 0 && ` · ${cleanResult.job_runs_deleted} job run(s) deleted`}
                                </p>
                                <div className="space-y-0.5 text-gray-600">
                                    {cleanResult.deleted.map((d, i) => <p key={i} className="text-green-700">✓ {d}</p>)}
                                    {cleanResult.errors.map((e, i) => <p key={i} className="text-red-600">✗ {e}</p>)}
                                </div>
                                <button onClick={() => setCleanResult(null)} className="mt-2 text-gray-400 hover:text-gray-600 cursor-pointer">Dismiss</button>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* ─── STEP 2: Preview ─────────────────────────────────────────── */}
            {step === "preview" && (
                <div className="space-y-5">
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-2">Sample File Preview</h3>
                        <p className="text-xs text-gray-500 mb-4">
                            Runs classification and extraction on the first file in the volume — lets you verify your schemas before processing all files.
                        </p>

                        {previewError && (
                            <div className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2 mb-3">
                                {previewError}
                            </div>
                        )}

                        {!previewRows.length && (
                            <button
                                onClick={runPreview}
                                disabled={previewLoading || !volumePath}
                                className="px-5 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors cursor-pointer"
                            >
                                {previewLoading ? "Analyzing…" : "▶ Run Preview on Sample File"}
                            </button>
                        )}

                        {previewLoading && (
                            <div className="mt-4 flex items-center gap-2 text-sm text-blue-600">
                                <span className="animate-spin inline-block">⟳</span>
                                Classifying and extracting sample file…
                            </div>
                        )}

                        {previewRows.length > 0 && (
                            <div className="space-y-4">
                                <div className="flex items-center gap-3 text-xs">
                                    <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded font-semibold">
                                        ✓ {previewDocType}
                                    </span>
                                    <span className="text-gray-500">{previewFile}</span>
                                </div>
                                <div className="overflow-x-auto rounded-xl border border-gray-200">
                                    <table className="w-full text-xs">
                                        <thead className="bg-gray-50 border-b border-gray-200">
                                            <tr>
                                                {Object.keys(previewRows[0]).map(k => (
                                                    <th key={k} className="text-left px-3 py-2 font-semibold text-gray-500 text-[10px] uppercase whitespace-nowrap">{k}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {previewRows.map((row, i) => (
                                                <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                                                    {Object.values(row).map((v, j) => (
                                                        <td key={j} className="px-3 py-2 text-gray-700 max-w-[200px] truncate">
                                                            {v == null ? <span className="text-gray-300">—</span> : String(v)}
                                                        </td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                <button
                                    onClick={runPreview}
                                    className="text-xs text-blue-600 hover:underline cursor-pointer"
                                >
                                    ↺ Rerun Preview
                                </button>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center justify-between">
                        <button onClick={() => setStep("configure")} className="text-sm text-gray-500 hover:text-gray-800 cursor-pointer">← Back</button>
                        <button onClick={() => setStep("run")} className="text-sm font-semibold px-5 py-2 rounded-lg bg-gray-900 text-white hover:bg-gray-700 transition-colors cursor-pointer">
                            Next: Run →
                        </button>
                    </div>
                </div>
            )}

            {/* ─── STEP 3: Run ─────────────────────────────────────────────── */}
            {step === "run" && (
                <div className="space-y-5">

                    {/* Mode selector */}
                    <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <span>⚡</span> Processing Mode
                        </h3>
                        <div className="grid grid-cols-2 gap-3">
                            {([
                                { id: "interactive" as ProcMode, icon: "🖱️", title: "Interactive", desc: "Process N files now, see results immediately." },
                                { id: "batch"       as ProcMode, icon: "🗓️", title: "Batch",       desc: "Schedule recurring processing on Databricks." },
                            ] as { id: ProcMode; icon: string; title: string; desc: string }[]).map(m => (
                                <button
                                    key={m.id}
                                    onClick={() => setMode(m.id)}
                                    className={`text-left p-4 rounded-xl border-2 transition-all cursor-pointer
                                        ${mode === m.id ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"}`}
                                >
                                    <div className="text-lg mb-1">{m.icon}</div>
                                    <div className="text-sm font-bold text-gray-800">{m.title}</div>
                                    <div className="text-xs text-gray-500 mt-0.5">{m.desc}</div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Interactive options */}
                    {mode === "interactive" && (
                        <div className="space-y-4">
                            {/* File count */}
                            <div className="bg-white rounded-xl border border-gray-200 p-5">
                                <h3 className="text-sm font-bold text-gray-800 mb-3">Number of Files to Process</h3>
                                <div className="flex items-center gap-4">
                                    <input
                                        type="range"
                                        min={1} max={999}
                                        value={batchSize}
                                        onChange={e => setBatchSize(Number(e.target.value))}
                                        className="flex-1 accent-blue-600"
                                    />
                                    <div className="flex items-center gap-2 shrink-0">
                                        <input
                                            type="number"
                                            min={1} max={999}
                                            value={batchSize}
                                            onChange={e => setBatchSize(Math.max(1, Math.min(999, Number(e.target.value))))}
                                            className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:ring-2 focus:ring-blue-400"
                                        />
                                        <span className="text-xs text-gray-400">files</span>
                                    </div>
                                </div>
                                <div className="flex gap-3 mt-2">
                                    {[5, 10, 25, 50, 999].map(n => (
                                        <button key={n} onClick={() => setBatchSize(n)}
                                            className={`text-xs px-2 py-1 rounded cursor-pointer ${batchSize === n ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200 text-gray-600"}`}>
                                            {n === 999 ? "All" : n}
                                        </button>
                                    ))}
                                </div>
                                <p className="text-[11px] text-gray-400 mt-2">999 = all new files in this run</p>
                            </div>

                            {/* Schema to apply */}
                            <div className="bg-white rounded-xl border border-gray-200 p-5">
                                <h3 className="text-sm font-bold text-gray-800 mb-1">Schemas to Apply</h3>
                                <p className="text-xs text-gray-500 mb-3">
                                    Each file will be classified first, then the matching schema is applied for structured extraction.
                                    Deselect any types you want to skip in this run.
                                </p>
                                {docTypeSchemas.length === 0 ? (
                                    <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                                        No schemas configured. Go to Schema Setup first.
                                    </div>
                                ) : (
                                    <div className="space-y-2">
                                        {docTypeSchemas.map(dt => {
                                            const checked = selectedTypes.includes(dt.doc_type);
                                            const fieldCount = dt.extraction_schema
                                                ? (() => { try { return (JSON.parse(dt.extraction_schema) as unknown[]).length; } catch { return 0; } })()
                                                : 0;
                                            return (
                                                <label key={dt.doc_type} className="flex items-center gap-3 cursor-pointer group py-1.5 border-b border-gray-50 last:border-0">
                                                    <input
                                                        type="checkbox"
                                                        checked={checked}
                                                        onChange={() => setSelectedTypes(prev =>
                                                            checked ? prev.filter(t => t !== dt.doc_type) : [...prev, dt.doc_type]
                                                        )}
                                                        className="w-4 h-4 accent-blue-600 cursor-pointer"
                                                    />
                                                    <div className="flex-1">
                                                        <span className="text-sm text-gray-800 font-medium font-mono group-hover:text-blue-700">
                                                            {dt.display_name || dt.doc_type}
                                                        </span>
                                                        <span className="ml-2 text-[10px] text-gray-400">
                                                            {fieldCount > 0 ? `${fieldCount} fields` : "no extraction fields"}
                                                        </span>
                                                    </div>
                                                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${fieldCount > 0 ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"}`}>
                                                        {fieldCount > 0 ? "✓ ready" : "—"}
                                                    </span>
                                                </label>
                                            );
                                        })}
                                    </div>
                                )}
                                <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-3 text-xs">
                                    <button onClick={() => setSelectedTypes(docTypeSchemas.map(d => d.doc_type))} className="text-blue-600 hover:underline cursor-pointer">Select all</button>
                                    <button onClick={() => setSelectedTypes([])} className="text-gray-400 hover:underline cursor-pointer">Clear all</button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Batch schedule */}
                    {mode === "batch" && (
                        <div className="bg-white rounded-xl border border-gray-200 p-5">
                            <h3 className="text-sm font-bold text-gray-800 mb-3">Schedule</h3>
                            <div className="grid grid-cols-2 gap-2 mb-3">
                                {[
                                    { id: "daily_2am",      label: "Daily 2 AM UTC" },
                                    { id: "daily_midnight", label: "Daily Midnight UTC" },
                                    { id: "weekly_mon",     label: "Weekly Mon 6 AM" },
                                    { id: "hourly",         label: "Hourly" },
                                    { id: "custom",         label: "Custom cron…" },
                                ].map(p => (
                                    <button
                                        key={p.id}
                                        onClick={() => applyPreset(p.id)}
                                        className={`text-xs px-3 py-2 rounded-lg border cursor-pointer transition-colors
                                            ${schedPreset === p.id ? "border-blue-500 bg-blue-50 text-blue-700 font-semibold" : "border-gray-200 hover:bg-gray-50 text-gray-600"}`}
                                    >
                                        {p.label}
                                    </button>
                                ))}
                            </div>
                            {schedPreset === "custom" && (
                                <input
                                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                                    placeholder="cron: 0 2 * * *"
                                    value={schedCron}
                                    onChange={e => setSchedCron(e.target.value)}
                                />
                            )}
                            {schedCron && schedPreset !== "custom" && (
                                <p className="text-[11px] text-gray-400 mt-1">Cron: <code>{schedCron}</code></p>
                            )}
                        </div>
                    )}

                    {/* Run summary */}
                    <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
                        <h3 className="text-sm font-bold text-gray-800 mb-3">Run Summary</h3>
                        <div className="space-y-1.5 text-xs text-gray-700">
                            <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Domain</span><span className="font-medium">{domainId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</span></div>
                            <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Volume</span><span className="font-mono">{volumePath || <em className="text-amber-500">not set</em>}</span></div>
                            <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Doc types</span><span>{selectedTypes.length ? selectedTypes.join(", ") : <em className="text-amber-500">none selected</em>}</span></div>
                            <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Mode</span><span>{mode}{mode === "interactive" ? ` — ${batchSize === 999 ? "all" : batchSize} files` : ""}</span></div>
                            {mode === "batch" && schedCron && <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Schedule</span><code>{schedCron}</code></div>}
                            <div className="flex gap-2"><span className="text-gray-400 w-28 shrink-0">Dedup</span><span>Already-processed files are skipped automatically</span></div>
                        </div>
                        {newDocs > 0 && !isRunning && (
                            <div className="mt-3 text-xs bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 text-amber-700">
                                <strong>{newDocs} new document{newDocs !== 1 ? "s" : ""}</strong> detected — not yet processed.
                            </div>
                        )}
                        {pipelineData?.run_url && !isRunning && (
                            <a href={pipelineData.run_url} target="_blank" rel="noreferrer"
                               className="mt-2 inline-block text-xs text-blue-600 hover:underline">
                                View last run in Databricks →
                            </a>
                        )}
                    </div>

                    {/* Pipeline stages — only show for runs triggered in THIS session
                        (prevents previous run's saved status from appearing on mount) */}
                    {sessionRunTriggered && (
                      pipelineData?.status === "running" ||
                      pipelineData?.status === "succeeded" ||
                      pipelineData?.status === "failed"
                    ) && (
                        <PipelineStagesDisplay
                            pipelineStatus={pipelineData!.status}
                            startTimeMs={pipelineData!.start_time_ms}
                            elapsedMs={pipelineData!.duration_ms}
                            tasks={pipelineData!.tasks}
                            runMeta={runMeta}
                        />
                    )}
                    {/* Show last-run summary when no session run has been triggered yet */}
                    {!sessionRunTriggered && pipelineData && pipelineData.status !== "never_run" && (
                        <div className="bg-gray-50 border border-gray-200 rounded-xl px-5 py-3 flex items-center justify-between text-xs">
                            <span className="text-gray-500 font-medium">Last run:</span>
                            <span className={`font-bold px-2 py-0.5 rounded-full ${
                                pipelineData.status === "succeeded" ? "bg-green-100 text-green-700" :
                                pipelineData.status === "failed"    ? "bg-red-100 text-red-700" :
                                pipelineData.status === "running"   ? "bg-blue-100 text-blue-600" :
                                "bg-gray-100 text-gray-500"}`}>
                                {pipelineData.status}
                            </span>
                            {pipelineData.run_url && (
                                <a href={pipelineData.run_url} target="_blank" rel="noreferrer"
                                   className="text-blue-600 hover:underline">View in Databricks →</a>
                            )}
                        </div>
                    )}

                    {/* Run button */}
                    <div className="flex items-center gap-3">
                        <button
                            onClick={doTrigger}
                            disabled={triggering || isRunning || !volumePath || selectedTypes.length === 0}
                            className={`flex-1 py-3.5 rounded-xl text-sm font-bold transition-all shadow-sm
                                ${triggering || isRunning ? "bg-blue-400 text-white cursor-not-allowed" :
                                  !volumePath || !selectedTypes.length ? "bg-gray-200 text-gray-400 cursor-not-allowed" :
                                  "bg-blue-600 text-white hover:bg-blue-700 shadow-md cursor-pointer"}`}
                        >
                            {triggering ? "Starting pipeline…" : isRunning ? "⟳ Pipeline Running…" :
                             mode === "interactive" ? `▶ Process ${batchSize === 999 ? "All" : batchSize} File${batchSize === 1 ? "" : "s"} Now` :
                             "▶ Start Batch Pipeline Run"}
                        </button>
                        <button onClick={() => setStep("configure")} className="text-sm text-gray-500 hover:text-gray-800 cursor-pointer">← Back</button>
                    </div>

                    {/* Processing Log */}
                    <div className="bg-white rounded-xl border border-gray-200">
                        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
                            <button
                                onClick={() => setShowLog(v => !v)}
                                className="flex items-center gap-2 text-sm font-bold text-gray-800 hover:text-blue-700 cursor-pointer"
                            >
                                <span>Processing Log</span>
                                <span className="text-gray-400 text-xs">{showLog ? "▲" : "▼"}</span>
                            </button>
                            <button
                                onClick={() => { setProcLog(null); fetchProcessingLog(); setShowLog(true); }}
                                disabled={logLoading}
                                className="text-xs text-blue-600 hover:underline cursor-pointer disabled:opacity-40 flex items-center gap-1"
                            >
                                {logLoading ? <span className="animate-spin">⟳</span> : "↺"} Refresh
                            </button>
                        </div>
                        {showLog && (
                            <div className="border-t border-gray-100 p-5">
                                {logLoading && <p className="text-xs text-gray-400">Loading…</p>}
                                {procLog && (
                                    <div className="space-y-4">
                                        {/* Stats */}
                                        <div className="grid grid-cols-4 gap-3">
                                            {[
                                                { label: "Total Logged",   val: procLog.stats.total_files },
                                                { label: "Succeeded",      val: procLog.stats.success_count },
                                                { label: "Failed",         val: procLog.stats.failed_count },
                                                { label: "Skipped",        val: procLog.stats.skipped_count },
                                            ].map(s => (
                                                <div key={s.label} className="text-center bg-gray-50 rounded-lg p-3">
                                                    <p className="text-xl font-bold text-gray-800">{s.val ?? 0}</p>
                                                    <p className="text-[10px] text-gray-400 font-medium">{s.label}</p>
                                                </div>
                                            ))}
                                        </div>

                                        {/* By type */}
                                        {procLog.by_doc_type.length > 0 && (
                                            <div>
                                                <p className="text-xs font-semibold text-gray-600 mb-2">By Document Type</p>
                                                <div className="space-y-1">
                                                    {procLog.by_doc_type.map(r => (
                                                        <div key={r.doc_type} className="flex items-center gap-3 text-xs">
                                                            <span className="text-gray-600 font-mono w-40 truncate">{r.doc_type}</span>
                                                            <div className="flex-1 bg-gray-100 rounded-full h-2">
                                                                <div className="bg-green-400 h-2 rounded-full" style={{ width: `${r.count > 0 ? (r.success / r.count) * 100 : 0}%` }} />
                                                            </div>
                                                            <span className="text-gray-500">{r.success}/{r.count}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Recent files */}
                                        {procLog.recent.length > 0 && (
                                            <div>
                                                <p className="text-xs font-semibold text-gray-600 mb-2">Recent Files</p>
                                                <div className="overflow-hidden rounded-xl border border-gray-200">
                                                    <table className="w-full text-xs">
                                                        <thead className="bg-gray-50 border-b border-gray-100">
                                                            <tr>
                                                                <th className="text-left px-3 py-2 text-[10px] text-gray-400 font-semibold uppercase">File</th>
                                                                <th className="text-left px-3 py-2 text-[10px] text-gray-400 font-semibold uppercase">Doc Type</th>
                                                                <th className="text-left px-3 py-2 text-[10px] text-gray-400 font-semibold uppercase">Status</th>
                                                                <th className="text-left px-3 py-2 text-[10px] text-gray-400 font-semibold uppercase">Processed At</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {procLog.recent.map((r, i) => (
                                                                <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                                                                    <td className="px-3 py-2 max-w-[160px] truncate text-gray-700" title={r.file_name}>{r.file_name}</td>
                                                                    <td className="px-3 py-2 text-gray-500">{r.doc_type || "—"}</td>
                                                                    <td className="px-3 py-2">
                                                                        <span className={`px-1.5 py-0.5 rounded font-semibold text-[10px]
                                                                            ${r.status === "success" ? "bg-green-100 text-green-700" :
                                                                              r.status === "failed"  ? "bg-red-100 text-red-700" :
                                                                              r.status === "skipped" ? "bg-gray-100 text-gray-500" :
                                                                              "bg-blue-100 text-blue-700"}`}>
                                                                            {r.status}
                                                                        </span>
                                                                    </td>
                                                                    <td className="px-3 py-2 text-gray-400">{r.processed_at ? new Date(r.processed_at).toLocaleString("en-US", { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" }) : "—"}</td>
                                                                </tr>
                                                            ))}
                                                        </tbody>
                                                    </table>
                                                </div>
                                                {/* Refresh is in the panel header */}
                                            </div>
                                        )}

                                        {procLog.recent.length === 0 && !logLoading && (
                                            <p className="text-xs text-gray-400">No files have been processed yet for this domain.</p>
                                        )}
                                    </div>
                                )}
                                {!procLog && !logLoading && (
                                    <p className="text-xs text-gray-400 py-2">Click ↺ Refresh to load the processing log.</p>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}


// ── Lightweight run history strip for the Document Library ───────────────────
// Shows last 5 pipeline runs + KPIs, with a link to Process Documents (no run trigger).
function RunHistoryStrip({
    domainId,
    onGoToProcess,
}: {
    domainId: string;
    onGoToProcess?: () => void;
}) {
    const [data, setData] = useState<PipelineData | null>(null);
    const [log,  setLog]  = useState<ProcessingLog | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let active = true;
        (async () => {
            try {
                const [r1, r2] = await Promise.all([
                    fetch(`/api/docintel/pipeline-status?domain_id=${encodeURIComponent(domainId)}`),
                    fetch(`/api/docintel/processing-log?domain_id=${encodeURIComponent(domainId)}&limit=5`),
                ]);
                if (active && r1.ok) setData(await r1.json());
                if (active && r2.ok) setLog(await r2.json());
            } catch { /* silent */ }
            if (active) setLoading(false);
        })();
        return () => { active = false; };
    }, [domainId]);

    const stats   = data?.stats ?? {};
    const isRunning = data?.status === "running";
    const recentRuns = data?.recent_runs ?? [];

    if (loading) {
        return (
            <div className="bg-white rounded-xl border border-gray-200 p-4 mb-5">
                <div className="flex items-center gap-2 text-xs text-gray-400 animate-pulse">
                    <span className="animate-spin">⟳</span> Loading pipeline status…
                </div>
            </div>
        );
    }

    return (
        <div className="bg-white rounded-xl border border-gray-200 mb-5 overflow-hidden">
            {/* Header row */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
                <div className="flex items-center gap-3">
                    <span className={`text-sm font-semibold ${
                        isRunning                       ? "text-blue-700" :
                        data?.status === "succeeded"    ? "text-green-700" :
                        data?.status === "failed"       ? "text-red-700" :
                        "text-gray-500"}`}>
                        {isRunning
                            ? "⟳ Pipeline running…"
                            : data?.status === "succeeded"
                                ? `✓ Last run succeeded · ${fmtMs(data.end_time_ms)}`
                                : data?.status === "failed"
                                    ? `✗ Last run failed · ${fmtMs(data.start_time_ms)}`
                                    : "Pipeline not yet run"}
                    </span>
                    {data?.run_url && (
                        <a href={data.run_url} target="_blank" rel="noreferrer"
                           className="text-xs text-blue-500 hover:underline">View run →</a>
                    )}
                </div>
                {onGoToProcess && data?.status !== "running" && (
                    <button
                        onClick={onGoToProcess}
                        className="text-xs text-gray-500 hover:text-blue-700 hover:underline cursor-pointer"
                    >
                        Process docs →
                    </button>
                )}
            </div>

            {/* KPI strip */}
            {(stats.docs_parsed != null || log?.stats?.total_files != null) && (
                <div className="grid grid-cols-5 divide-x divide-gray-100 border-b border-gray-100">
                    {[
                        { label: "Docs Parsed",      val: stats.docs_parsed },
                        { label: "Fields Extracted", val: stats.fields_extracted },
                        { label: "Chunks Indexed",   val: stats.chunks_indexed },
                        { label: "Files Logged",     val: log?.stats?.total_files },
                        { label: "Succeeded",        val: log?.stats?.success_count },
                    ].map(({ label, val }) => (
                        <div key={label} className="px-4 py-2.5 text-center">
                            <p className="text-base font-bold text-gray-800">
                                {val == null ? <span className="text-gray-300 text-sm">—</span> : val.toLocaleString()}
                            </p>
                            <p className="text-[10px] text-gray-400 font-medium leading-none mt-0.5">{label}</p>
                        </div>
                    ))}
                </div>
            )}

            {/* Last 5 runs */}
            {recentRuns.length > 0 && (
                <div className="overflow-hidden">
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wide px-5 pt-3 pb-1">Recent Runs</p>
                    <table className="w-full text-xs">
                        <thead className="bg-gray-50 border-b border-gray-100">
                            <tr>
                                <th className="text-left px-5 py-2 text-[10px] text-gray-400 font-semibold uppercase">Status</th>
                                <th className="text-left px-4 py-2 text-[10px] text-gray-400 font-semibold uppercase">Started</th>
                                <th className="text-right px-4 py-2 text-[10px] text-gray-400 font-semibold uppercase">Duration</th>
                                <th className="text-right px-4 py-2 text-[10px] text-gray-400 font-semibold uppercase">Run ID</th>
                                <th className="px-4 py-2" />
                            </tr>
                        </thead>
                        <tbody>
                            {recentRuns.slice(0, 5).map((run, i) => (
                                <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                                    <td className="px-5 py-2">
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                            run.status === "SUCCESS"    ? "bg-green-100 text-green-700" :
                                            run.status === "FAILED"     ? "bg-red-100 text-red-700" :
                                            run.status === "RUNNING"    ? "bg-blue-100 text-blue-700" :
                                            "bg-gray-100 text-gray-500"}`}>
                                            {run.status}
                                        </span>
                                    </td>
                                    <td className="px-4 py-2 text-gray-500">{fmtMs(run.start_time_ms)}</td>
                                    <td className="px-4 py-2 text-right text-gray-500">{fmtDur(run.duration_ms)}</td>
                                    <td className="px-4 py-2 text-right text-gray-400">{run.run_id}</td>
                                    <td className="px-4 py-2 text-right">
                                        {run.run_url && <a href={run.run_url} target="_blank" rel="noreferrer" className="text-blue-500 hover:underline text-[10px]">↗</a>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Empty state */}
            {!recentRuns.length && !loading && (
                <div className="px-5 py-4 text-xs text-gray-400">
                    No pipeline runs yet.{" "}
                    {onGoToProcess && (
                        <button onClick={onGoToProcess} className="text-blue-600 hover:underline cursor-pointer">
                            Go to Process Documents →
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}


function DocumentLibrary({ onBack, domainId = "supply_chain", onGoToProcess }: { onBack: () => void; domainId?: string; onGoToProcess?: () => void }) {
    const [docs, setDocs] = useState<LibraryDoc[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [search, setSearch] = useState("");
    const [typeFilter, setTypeFilter] = useState("all");
    const [selectedDoc, setSelectedDoc] = useState<LibraryDoc | null>(null);
    const [detailDoc, setDetailDoc] = useState<any | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [expandedText, setExpandedText] = useState(false);
    const [docIncidents, setDocIncidents] = useState<any | null>(null);
    // Unmatched docs (no schema)
    const [unmatchedDocs, setUnmatchedDocs] = useState<{ doc_id: string; filename: string; doc_type: string; reason: string; processed_ts: string }[]>([]);
    const [unmatchedLoading, setUnmatchedLoading] = useState(false);
    const [showUnmatched, setShowUnmatched] = useState(false);

    const loadDocs = useCallback(() => {
        setLoading(true);
        fetch(`/api/docintel/document-library?domain_id=${encodeURIComponent(domainId)}`)
            .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
            .then(d => { setDocs(d.documents ?? []); setLoading(false); })
            .catch(e => { setError(String(e)); setLoading(false); });
    }, [domainId]);

    const loadUnmatched = useCallback(async () => {
        setUnmatchedLoading(true);
        try {
            const r = await fetch(`/api/docintel/unmatched-docs?domain_id=${encodeURIComponent(domainId)}&limit=100`);
            if (r.ok) {
                const d = await r.json();
                setUnmatchedDocs(d.unmatched || []);
            }
        } catch { /* silent */ }
        setUnmatchedLoading(false);
    }, [domainId]);

    useEffect(() => { loadDocs(); }, [loadDocs]);

    // Auto-highlight a document coming from an external link (e.g. Action Center)
    useEffect(() => {
        try {
            const raw = sessionStorage.getItem("docintel_highlight_doc");
            if (!raw) return;
            sessionStorage.removeItem("docintel_highlight_doc");
            const payload: { doc_id?: string } = JSON.parse(raw);
            if (!payload.doc_id) return;
            // Wait for docs to load then open the matching one
            const tryOpen = (attempts = 0) => {
                setDocs(current => {
                    const match = current.find(d => d.doc_id === payload.doc_id);
                    if (match) {
                        loadDetail(match);
                    } else if (attempts < 8) {
                        setTimeout(() => tryOpen(attempts + 1), 500);
                    }
                    return current;
                });
            };
            tryOpen();
        } catch { /* silent */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (showUnmatched && unmatchedDocs.length === 0 && !unmatchedLoading) {
            loadUnmatched(); // eslint-disable-line react-hooks/exhaustive-deps
        }
    }, [showUnmatched]); // intentionally only triggers on toggle

    async function loadDetail(doc: LibraryDoc) {
        setSelectedDoc(doc);
        setDetailDoc(null);
        setDocIncidents(null);
        setDetailLoading(true);
        setExpandedText(false);
        try {
            const [detailRes, incRes] = await Promise.all([
                fetch(`/api/docintel/document-detail?doc_id=${encodeURIComponent(doc.doc_id)}&domain_id=${encodeURIComponent(domainId)}`),
                fetch(`/api/docintel/doc-incidents?doc_id=${encodeURIComponent(doc.doc_id)}&domain_id=${encodeURIComponent(domainId)}`),
            ]);
            if (detailRes.ok) setDetailDoc(await detailRes.json());
            if (incRes.ok) setDocIncidents(await incRes.json());
        } catch {}
        setDetailLoading(false);
    }

    const docTypes = Array.from(new Set(docs.map(d => d.doc_type))).sort();
    const filtered = docs.filter(d => {
        const matchType = typeFilter === "all" || d.doc_type === typeFilter;
        const q = search.toLowerCase();
        const matchSearch = !q || d.filename.toLowerCase().includes(q)
            || d.doc_type_label.toLowerCase().includes(q)
            || d.text_preview?.toLowerCase().includes(q);
        return matchType && matchSearch;
    });

    function fmtTs(ts: string) {
        if (!ts) return "";
        const d = new Date(ts);
        return isNaN(d.getTime()) ? ts : d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    if (selectedDoc) {
        const d = detailDoc ?? selectedDoc;
        const colorCls = DOC_TYPE_COLORS[d.doc_type] ?? "bg-gray-100 text-gray-800 border-gray-200";
        const fullText: string = d.raw_text ?? d.text_preview ?? "";
        return (
            <div className="min-h-screen bg-gray-50 p-6">
                <div className="max-w-5xl mx-auto">
                    <button onClick={() => setSelectedDoc(null)} className="mb-4 text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1">
                        ← Back to Library
                    </button>
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                        {/* Header */}
                        <div className="flex items-start justify-between gap-4 mb-6">
                            <div>
                                <h2 className="text-xl font-bold text-gray-900 mb-1">{d.filename}</h2>
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${colorCls}`}>{d.doc_type_label ?? d.doc_type}</span>
                                    <span className="text-xs text-gray-400">Processed: {fmtTs(d.processed_ts)}</span>
                                    {d.est_word_count && <span className="text-xs text-gray-400">~{Number(d.est_word_count).toLocaleString()} words</span>}
                                    {d.entity_count > 0 && <span className="text-xs text-gray-400">{d.entity_count} entities</span>}
                                </div>
                            </div>
                            {detailLoading && <span className="text-xs text-gray-400 animate-pulse">Loading full detail…</span>}
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            {/* Extracted Fields */}
                            <div>
                                <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-1.5">
                                    <span className="text-base">🔍</span> AI-Extracted Fields
                                </h3>
                                {Object.keys(d.extracted_fields ?? {}).length > 0 ? (
                                    <div className="space-y-2">
                                        {Object.entries(d.extracted_fields).map(([k, v]) => (
                                            <div key={k} className="bg-gray-50 rounded-md px-3 py-2 border border-gray-100">
                                                <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-0.5">{k.replace(/_/g, " ")}</p>
                                                <p className="text-sm text-gray-800">{String(v)}</p>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p className="text-sm text-gray-400 italic">No structured fields extracted (or pipeline not yet run)</p>
                                )}
                            </div>

                            {/* Related Entities */}
                            <div>
                                <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-1.5">
                                    <span className="text-base">🕸</span> Related Ontology Entities
                                </h3>
                                {(d.related_entities ?? []).length > 0 ? (
                                    <div className="flex flex-wrap gap-1.5">
                                        {(d.related_entities as any[]).map((e: any, i: number) => (
                                            <div key={i} className="bg-white border border-gray-200 rounded-md px-2 py-1 text-xs">
                                                <span className="font-medium text-gray-800">{e.display_name}</span>
                                                <span className="text-gray-400 ml-1">· {e.entity_type}</span>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p className="text-sm text-gray-400 italic">No mapped entities (or ontology pipeline not yet run)</p>
                                )}
                            </div>

                            {/* Incident Connections */}
                            {docIncidents && (
                                <div className="border-t border-gray-100 pt-4">
                                    <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-1.5">
                                        <span className="text-base">🚨</span> Incident Connections
                                    </h3>

                                    {/* Linked incidents */}
                                    {(docIncidents.linked_incidents ?? []).length > 0 && (
                                        <div className="mb-3">
                                            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Linked to these incidents</p>
                                            <div className="space-y-1.5">
                                                {(docIncidents.linked_incidents as any[]).map((inc: any, i: number) => (
                                                    <div key={i} className="flex items-start gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                                                        <span className="text-[10px] mt-0.5">🔗</span>
                                                        <div className="min-w-0 flex-1">
                                                            <p className="text-xs font-semibold text-red-800">{inc.incident_id}</p>
                                                            <p className="text-[10px] text-red-700 truncate">{inc.title}</p>
                                                            <div className="flex gap-1.5 mt-0.5">
                                                                <span className={`text-[9px] font-semibold px-1 py-0.5 rounded ${
                                                                    inc.severity === "critical" ? "bg-red-200 text-red-800" :
                                                                    inc.severity === "high"     ? "bg-orange-100 text-orange-800" :
                                                                    "bg-gray-100 text-gray-600"}`}>
                                                                    {inc.severity?.toUpperCase()}
                                                                </span>
                                                                <span className="text-[9px] text-gray-400">{inc.status}</span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Suggested incidents */}
                                    {(docIncidents.suggested_incidents ?? []).length > 0 && (
                                        <div>
                                            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Also relevant to</p>
                                            <div className="space-y-1.5">
                                                {(docIncidents.suggested_incidents as any[]).map((inc: any, i: number) => (
                                                    <div key={i} className="flex items-start gap-2 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                                                        <span className="text-[10px] mt-0.5">💡</span>
                                                        <div className="min-w-0 flex-1">
                                                            <p className="text-xs font-semibold text-amber-900">{inc.incident_id}</p>
                                                            <p className="text-[10px] text-amber-800 truncate">{inc.title}</p>
                                                            <p className="text-[9px] text-gray-500 mt-0.5 italic">{inc.relevance_note}</p>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {(docIncidents.linked_incidents ?? []).length === 0 && (docIncidents.suggested_incidents ?? []).length === 0 && (
                                        <p className="text-xs text-gray-400 italic">No incident connections found for this document type.</p>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Full text */}
                        <div className="mt-6">
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
                                    <span className="text-base">📄</span> Document Text
                                </h3>
                                {fullText.length > 600 && (
                                    <button onClick={() => setExpandedText(e => !e)} className="text-xs text-blue-600 hover:text-blue-800">
                                        {expandedText ? "Show less" : "Show full text"}
                                    </button>
                                )}
                            </div>
                            <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 max-h-80 overflow-y-auto">
                                <pre className="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed font-mono">
                                    {expandedText ? fullText : (fullText.slice(0, 600) + (fullText.length > 600 ? "\n\n[…truncated — click Show full text]" : ""))}
                                </pre>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-50 p-6">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">Document Library</h1>
                        <p className="text-sm text-gray-500 mt-0.5">
                            All documents processed through the IDP pipeline · <code className="bg-gray-100 px-1 rounded">jai_docintel.raw.parsed_documents</code>
                        </p>
                    </div>
                    <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5 rounded-md border border-gray-200 hover:bg-gray-100">
                        ← Back
                    </button>
                </div>

                {/* Run history strip — no trigger button here; link to Process Docs */}
                <RunHistoryStrip domainId={domainId} onGoToProcess={onGoToProcess} />

                {/* Filters */}
                <div className="flex gap-3 mb-5 flex-wrap">
                    <input
                        value={search} onChange={e => setSearch(e.target.value)}
                        placeholder="Search filename, type, content…"
                        className="flex-1 min-w-48 text-sm border border-gray-300 rounded-lg px-3 py-2"
                    />
                    <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
                        className="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white">
                        <option value="all">All types</option>
                        {docTypes.map(t => (
                            <option key={t} value={t}>{t.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</option>
                        ))}
                    </select>
                    <span className="self-center text-sm text-gray-400">{filtered.length} document{filtered.length !== 1 ? "s" : ""}</span>
                </div>

                {loading && (
                    <div className="text-center py-16 text-gray-400">
                        <div className="text-3xl mb-2 animate-spin inline-block">⟳</div>
                        <p>Loading document catalog…</p>
                    </div>
                )}

                {error && (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700 mb-4">
                        <strong>Could not load library:</strong> {error}
                        <p className="mt-1 text-xs text-red-500">Make sure the IDP pipeline (notebook 03_idp_pipeline) has been run at least once.</p>
                    </div>
                )}

                {!loading && !error && filtered.length === 0 && (
                    <div className="text-center py-16 text-gray-400">
                        <div className="text-4xl mb-3">📂</div>
                        <p className="font-medium">No documents found</p>
                        <p className="text-sm mt-1">
                            {docs.length === 0
                                ? "The IDP pipeline hasn't been run yet. Upload PDFs and run the pipeline first."
                                : "No documents match your current filters."}
                        </p>
                    </div>
                )}

                {/* Document grid */}
                {!loading && filtered.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        {/* Unmatched docs banner — shown only after docs load */}
                        {!loading && docs.length > 0 && (
                            <div className={`mb-4 rounded-xl border overflow-hidden transition-all
                                ${unmatchedDocs.length > 0 && !unmatchedLoading
                                    ? "border-amber-200 bg-amber-50"
                                    : "border-gray-200 bg-white"}`}>
                                <button
                                    onClick={() => {
                                        if (!showUnmatched && unmatchedDocs.length === 0) loadUnmatched();
                                        setShowUnmatched(v => !v);
                                    }}
                                    className="w-full flex items-center justify-between px-4 py-3 cursor-pointer hover:opacity-90 transition-opacity"
                                >
                                    <div className="flex items-center gap-2">
                                        <span className="text-base">⚠️</span>
                                        <span className={`text-sm font-semibold
                                            ${unmatchedDocs.length > 0 ? "text-amber-800" : "text-gray-600"}`}>
                                            Documents Without a Schema
                                        </span>
                                        {unmatchedLoading && (
                                            <span className="text-xs text-gray-400 animate-pulse">Checking…</span>
                                        )}
                                        {!unmatchedLoading && unmatchedDocs.length > 0 && (
                                            <span className="text-[11px] bg-amber-200 text-amber-800 px-2 py-0.5 rounded-full font-bold">
                                                {unmatchedDocs.length} file{unmatchedDocs.length !== 1 ? "s" : ""}
                                            </span>
                                        )}
                                        {!unmatchedLoading && unmatchedDocs.length === 0 && showUnmatched && (
                                            <span className="text-[11px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold">✓ All matched</span>
                                        )}
                                    </div>
                                    <span className="text-xs text-gray-400">{showUnmatched ? "▲ Hide" : "▼ Show"}</span>
                                </button>
                                {showUnmatched && (
                                    <div className="border-t border-amber-200 p-4">
                                        {unmatchedLoading && (
                                            <p className="text-xs text-gray-400 py-2">Loading unmatched documents…</p>
                                        )}
                                        {!unmatchedLoading && unmatchedDocs.length === 0 && (
                                            <p className="text-xs text-green-700 py-2">
                                                All parsed documents have a matching extraction schema. 🎉
                                            </p>
                                        )}
                                        {!unmatchedLoading && unmatchedDocs.length > 0 && (
                                            <div className="space-y-3">
                                                <p className="text-xs text-amber-700">
                                                    These files were parsed and indexed but could not be fully extracted because no schema is configured for their document type.
                                                    Go to <strong>Schema Setup</strong> to add the missing document types, then re-run the pipeline.
                                                </p>
                                                <div className="overflow-hidden rounded-lg border border-amber-200">
                                                    <table className="w-full text-xs">
                                                        <thead className="bg-amber-100 border-b border-amber-200">
                                                            <tr>
                                                                <th className="text-left px-3 py-2 font-semibold text-amber-800 text-[10px] uppercase">Filename</th>
                                                                <th className="text-left px-3 py-2 font-semibold text-amber-800 text-[10px] uppercase">Predicted Type</th>
                                                                <th className="text-left px-3 py-2 font-semibold text-amber-800 text-[10px] uppercase">Reason</th>
                                                                <th className="text-left px-3 py-2 font-semibold text-amber-800 text-[10px] uppercase">Parsed At</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {unmatchedDocs.map((u, i) => (
                                                                <tr key={i} className="border-t border-amber-100 hover:bg-amber-50">
                                                                    <td className="px-3 py-2 text-gray-700 max-w-[180px] truncate font-medium" title={u.filename}>{u.filename}</td>
                                                                    <td className="px-3 py-2 text-gray-500">{u.doc_type || <em className="text-gray-300">not classified</em>}</td>
                                                                    <td className="px-3 py-2 text-amber-700">{u.reason}</td>
                                                                    <td className="px-3 py-2 text-gray-400">
                                                                        {u.processed_ts ? new Date(u.processed_ts).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"}
                                                                    </td>
                                                                </tr>
                                                            ))}
                                                        </tbody>
                                                    </table>
                                                </div>
                                                <div className="flex items-center gap-3 pt-1">
                                                    <button
                                                        onClick={loadUnmatched}
                                                        className="text-xs text-amber-700 hover:underline cursor-pointer"
                                                    >↺ Refresh</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {filtered.map((doc) => {
                            const colorCls = DOC_TYPE_COLORS[doc.doc_type] ?? "bg-gray-100 text-gray-800 border-gray-200";
                            const fieldKeys = Object.keys(doc.extracted_fields ?? {});
                            return (
                                <div
                                    key={doc.doc_id}
                                    onClick={() => loadDetail(doc)}
                                    className="bg-white rounded-xl border border-gray-200 p-4 cursor-pointer hover:shadow-md hover:border-blue-300 transition-all group"
                                >
                                    {/* Type badge + filename */}
                                    <div className="mb-2">
                                        <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full border mb-2 ${colorCls}`}>
                                            {doc.doc_type_label}
                                        </span>
                                        <h3 className="text-sm font-semibold text-gray-900 leading-snug break-all group-hover:text-blue-700">
                                            {doc.filename}
                                        </h3>
                                    </div>

                                    {/* Stats row */}
                                    <div className="flex gap-3 text-[10px] text-gray-400 mb-2.5">
                                        <span>~{Number(doc.est_word_count).toLocaleString()} words</span>
                                        {doc.entity_count > 0 && <span>🕸 {doc.entity_count} entities</span>}
                                        {fieldKeys.length > 0 && <span>🔍 {fieldKeys.length} fields</span>}
                                    </div>

                                    {/* Text preview */}
                                    {doc.text_preview && (
                                        <p className="text-xs text-gray-500 leading-relaxed line-clamp-3 mb-2.5">
                                            {doc.text_preview}
                                        </p>
                                    )}

                                    {/* Key extracted fields preview (up to 3) */}
                                    {fieldKeys.length > 0 && (
                                        <div className="space-y-1 border-t border-gray-100 pt-2">
                                            {fieldKeys.slice(0, 3).map(k => (
                                                <div key={k} className="flex gap-1.5 text-[10px]">
                                                    <span className="text-gray-400 font-medium shrink-0">{k.replace(/_/g, " ")}:</span>
                                                    <span className="text-gray-700 truncate">{String(doc.extracted_fields[k])}</span>
                                                </div>
                                            ))}
                                            {fieldKeys.length > 3 && <p className="text-[10px] text-gray-400">+{fieldKeys.length - 3} more fields</p>}
                                        </div>
                                    )}

                                    <div className="mt-2.5 text-[10px] text-gray-300 border-t border-gray-100 pt-2">
                                        {fmtTs(doc.processed_ts)}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}

export default function DocumentIntelligencePage({
  domain,
  initialStep,
}: {
  domain?: { domain_id: string; name: string; schema_ready?: boolean };
  initialStep?: string;
}) {
  const ctx = useDomain();
  const resolvedDomain = domain ?? ctx.domain;
  const domainId   = resolvedDomain?.domain_id || "supply_chain";
  const domainName = resolvedDomain?.name       || "Supply Chain";

  // Sub-tab state: "schema" | "process"
  const [activeSubTab, setActiveSubTab] = useState<"schema" | "process">("schema");
  const [schemaReady,  setSchemaReady]  = useState<boolean>(resolvedDomain?.schema_ready ?? false);

  // If initialStep is "library", render DocumentLibrary immediately
  if (initialStep === "library") {
    return (
      <div className="min-h-screen bg-gray-50">
        <DocumentLibrary onBack={() => {}} domainId={domainId} onGoToProcess={() => setActiveSubTab("process")} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Sub-tab navigation */}
      <WizardStepBar
        activeStep={activeSubTab as "schema" | "process"}
        schemaReady={schemaReady}
        onStep={s => setActiveSubTab(s)}
      />

      {/* Schema Setup */}
      {activeSubTab === "schema" && (
        <DomainSchemaWizard
          domainId={domainId}
          domainName={domainName}
          onSchemaConfirmed={() => {
            setSchemaReady(true);
            setActiveSubTab("process");
          }}
        />
      )}

      {/* Process Documents */}
      {activeSubTab === "process" && (
        <div className="flex-1">
          <ProcessDocuments
            domainId={domainId}
            onRunComplete={() => {}}
          />
        </div>
      )}
    </div>
  );
}
