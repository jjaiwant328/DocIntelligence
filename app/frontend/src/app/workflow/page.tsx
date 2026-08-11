"use client";

import { useState } from "react";
import { apiCall } from "@/lib/api-config";

interface Evidence {
  document_id: string;
  locator?: string;
  source_text?: string;
  confidence?: number | null;
  method?: string;
}
interface StepRecord {
  id: string;
  skill: string;
  status: string;
  outputs: Record<string, unknown>;
  evidence: Evidence[];
  error?: string | null;
  attempts?: number;
}
interface WorkflowRun {
  template_id: string;
  template_version: string;
  domain: string;
  status: string;
  work_object_id: string;
  halted_at?: string | null;
  steps: StepRecord[];
}

const DOMAINS = [
  { id: "compliance", label: "Compliance — New Store Feasibility", project: "Store 1827" },
  { id: "supply_chain", label: "Supply Chain — Supplier Qualification", project: "Supplier ABC" },
];

function statusColor(s: string): string {
  if (s === "completed" || s === "ok" || s === "satisfied") return "bg-green-100 text-green-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  if (s === "failed" || s === "error") return "bg-red-100 text-red-800";
  if (s === "gap") return "bg-orange-100 text-orange-800";
  if (s === "insufficient_evidence") return "bg-gray-200 text-gray-700";
  return "bg-blue-100 text-blue-800";
}

export default function WorkflowPage() {
  const [domainId, setDomainId] = useState("compliance");
  const [project, setProject] = useState("Store 1827");
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  async function execute(approve: boolean) {
    setLoading(true);
    setError(null);
    try {
      const result = await apiCall<WorkflowRun>("/api/docintel/workflow-run", {
        method: "POST",
        body: JSON.stringify({
          template: "due_diligence",
          domain_id: domainId,
          project,
          approve,
        }),
      });
      setRun(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-gray-800">Workflow Runner</h1>
      <p className="text-sm text-gray-500 mb-4">
        One deterministic <span className="font-mono">due_diligence</span> template,
        composed of reusable skills. Switch the domain and the same engine runs
        Compliance or Supply Chain — no engine or skill change.
      </p>

      {/* Run panel */}
      <div className="border border-gray-200 rounded-lg p-4 bg-white flex flex-wrap gap-3 items-end">
        <label className="flex flex-col text-xs text-gray-600">
          Domain / Use Case
          <select
            className="mt-1 border rounded px-2 py-1 text-sm min-w-[280px]"
            value={domainId}
            onChange={(e) => {
              const d = DOMAINS.find((x) => x.id === e.target.value)!;
              setDomainId(d.id);
              setProject(d.project);
            }}
          >
            {DOMAINS.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Project / Case
          <input
            className="mt-1 border rounded px-2 py-1 text-sm"
            value={project}
            onChange={(e) => setProject(e.target.value)}
          />
        </label>
        <button
          onClick={() => execute(false)}
          disabled={loading}
          className="bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50"
        >
          {loading ? "Running…" : "Run Workflow"}
        </button>
      </div>

      {error && (
        <div className="mt-4 border border-red-200 bg-red-50 text-red-700 text-sm rounded p-3">
          {error}
        </div>
      )}

      {run && (
        <div className="mt-6">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-sm text-gray-600">
              {run.template_id} v{run.template_version} · {run.domain}
              {run.work_object_id ? ` · ${run.work_object_id}` : ""}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded ${statusColor(run.status)}`}>
              {run.status}
            </span>
          </div>

          {run.status === "pending_approval" && (
            <div className="mb-4 border border-amber-200 bg-amber-50 rounded p-3 text-sm">
              Workflow halted at the human-approval gate before creating actions.
              <button
                onClick={() => execute(true)}
                disabled={loading}
                className="ml-3 bg-amber-600 text-white rounded px-3 py-1 text-xs disabled:opacity-50"
              >
                Approve &amp; create draft actions
              </button>
            </div>
          )}

          {/* Step inspector */}
          <ol className="space-y-2">
            {run.steps.map((s) => {
              const key = s.id;
              const open = expanded[key];
              return (
                <li key={key} className="border border-gray-200 rounded-lg bg-white">
                  <button
                    className="w-full flex items-center gap-3 px-4 py-2 text-left"
                    onClick={() => setExpanded((x) => ({ ...x, [key]: !x[key] }))}
                  >
                    <span className="font-mono text-xs text-gray-400">{s.id}</span>
                    <span className="text-sm font-medium text-gray-800">{s.skill}</span>
                    <span className={`ml-auto text-xs px-2 py-0.5 rounded ${statusColor(s.status)}`}>
                      {s.status}
                    </span>
                    <span className="text-xs text-gray-400">
                      {s.evidence.length} evidence
                    </span>
                  </button>
                  {open && (
                    <div className="px-4 pb-3 border-t border-gray-100">
                      {s.error && (
                        <p className="text-xs text-red-600 mt-2">Error: {s.error}</p>
                      )}
                      <pre className="mt-2 text-xs bg-gray-50 rounded p-2 overflow-x-auto">
                        {JSON.stringify(s.outputs, null, 2)}
                      </pre>
                      {s.evidence.length > 0 && (
                        <div className="mt-2">
                          <p className="text-xs font-semibold text-gray-500">Evidence</p>
                          <ul className="mt-1 space-y-1">
                            {s.evidence.map((ev, i) => (
                              <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2">
                                <span className="font-mono">{ev.document_id}</span>
                                {ev.method ? ` · ${ev.method}` : ""}
                                {ev.source_text ? ` — ${ev.source_text.slice(0, 160)}` : ""}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </main>
  );
}
