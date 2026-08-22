"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";
import { FormattedOutputs } from "@/components/FormattedOutputs";

interface RunRow {
  run_id: string; project_id?: string; template_id: string;
  work_object_id?: string; status: string; halted_at?: string;
  step_count?: number; error_count?: number; created_at?: string;
  saved?: boolean; label?: string;
}
interface StepRec { id: string; skill: string; status: string; outputs?: Record<string, unknown>; evidence?: { document_id: string; source_text?: string }[]; error?: string | null }
interface FullRun { template_id: string; domain: string; status: string; steps: StepRec[] }
interface ActionRow { action_id: string; action_type: string; description: string; priority: string; status: string; }
interface OntNode { id: string; label: string; type: string; }
interface OntEdge { source: string; target: string; label: string; }

function overlayToPlatform(d: string): string {
  return d === "supply_chain" ? "supply_chain" : "compliance_due_diligence";
}
function statusColor(s: string): string {
  if (["ok", "completed", "satisfied", "CLOSED", "ASSIGNED"].includes(s)) return "bg-green-100 text-green-800";
  if (["error", "failed"].includes(s)) return "bg-red-100 text-red-800";
  if (s === "DRAFT") return "bg-amber-100 text-amber-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  return "bg-blue-100 text-blue-800";
}

export default function ExecutionsTab({ domain }: { domain?: DomainInfo }) {
  const { project } = useDomain();
  const overlay = (domain?.domain_id ?? "compliance") === "supply_chain" ? "supply_chain" : "compliance";
  const platformDomain = overlayToPlatform(overlay);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [graph, setGraph] = useState<{ nodes: OntNode[]; edges: OntEdge[] } | null>(null);
  const [tab, setTab] = useState<"runs" | "actions" | "entities">("runs");
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<FullRun | null>(null);
  const [openRunId, setOpenRunId] = useState<string | null>(null);

  async function reopen(runId: string) {
    setOpenRunId(runId); setOpenRun(null);
    try {
      const r = await apiCall<{ run: FullRun | null; error?: string }>(`/api/docintel/workflow-run/${encodeURIComponent(runId)}`);
      setOpenRun(r.run);
    } catch { setOpenRun(null); }
  }

  function refresh() {
    const pid = project?.project_id;
    const projQ = pid ? `&project_id=${encodeURIComponent(pid)}` : "";
    apiCall<{ runs: RunRow[] }>(`/api/docintel/workflow-runs?domain_id=${overlay}${projQ}`)
      .then((r) => setRuns(r.runs || [])).catch(() => setRuns([]));
    // Actions are tied to a project via action_log.incident_ref = project_id
    // (set by the create_action skill). Scope to the selected project.
    const actQ = pid ? `&incident_ref=${encodeURIComponent(pid)}` : "";
    apiCall<{ actions: ActionRow[] }>(`/api/docintel/action-log?domain_id=${platformDomain}${actQ}`)
      .then((r) => setActions(r.actions || [])).catch(() => setActions([]));
    apiCall<{ nodes: OntNode[]; edges: OntEdge[] }>(`/api/docintel/ontology-graph?domain_id=${platformDomain}`)
      .then((r) => setGraph({ nodes: r.nodes || [], edges: r.edges || [] })).catch(() => setGraph(null));
  }
  useEffect(refresh, [platformDomain, overlay, project?.project_id]);

  // group workflow runs by project so the Executions tab reads project-first
  const runsByProject: Record<string, RunRow[]> = {};
  runs.forEach((r) => {
    const k = r.project_id || "(no project)";
    (runsByProject[k] = runsByProject[k] || []).push(r);
  });

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">
          Runs and their outputs for <span className="font-semibold text-gray-700">{domain?.name ?? overlay}</span>
          {project?.project_id
            ? <> · project <span className="font-semibold text-gray-700">📁 {project.name || project.project_id}</span></>
            : <> · all projects</>} —
          actions, entities, and findings all trace back to a run.
        </p>
        <button onClick={refresh} className="text-xs text-blue-600">↻ Refresh</button>
      </div>

      <div className="flex gap-1 border-b border-gray-200 mb-4">
        {[["runs", "Runs"], ["actions", `Actions (${actions.length})`], ["entities", "Entities / Coverage"]].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id as typeof tab)}
            className={`text-sm px-3 py-1.5 -mb-px border-b-2 ${tab === id ? "border-blue-600 text-blue-700 font-medium" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {label}
          </button>
        ))}
      </div>

      {error && <div className="mb-3 text-xs text-red-600">{error}</div>}

      {tab === "runs" && (
        <div className="space-y-5">
          {runs.length === 0 && (
            <p className="text-sm text-gray-400">
              No runs yet{project?.project_id ? " for this project" : ""} — run a workflow from the Workflows tab.
            </p>
          )}

          {/* Workflow runs, grouped by project/case */}
          {Object.entries(runsByProject).map(([proj, projRuns]) => (
            <div key={proj}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-semibold text-gray-800">📁 {proj}</span>
                <span className="text-xs text-gray-400">{projRuns.length} run(s)</span>
              </div>
              <div className="space-y-2">
                {projRuns.map((r) => (
                  <div key={r.run_id + (r.created_at ?? "")} className="border border-gray-200 rounded-lg bg-white px-3 py-2">
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-sm font-medium text-gray-800">{r.template_id}</span>
                      <span className={`px-1.5 py-0.5 rounded ${statusColor(r.status)}`}>{r.status}</span>
                      {r.saved && <span className="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">★ saved</span>}
                      {r.work_object_id && <span className="font-mono text-gray-400">{r.work_object_id}</span>}
                      <span className="text-gray-400">{r.step_count ?? 0} step(s){(r.error_count ?? 0) > 0 ? ` · ${r.error_count} error(s)` : ""}</span>
                      {r.halted_at && <span className="text-amber-600">halted at {r.halted_at}</span>}
                      <span className="ml-auto text-gray-400">{String(r.created_at || "").slice(0, 19)}</span>
                      {r.saved && (
                        <button onClick={() => (openRunId === r.run_id ? setOpenRunId(null) : reopen(r.run_id))}
                          className="text-blue-600">{openRunId === r.run_id ? "Hide" : "Open"}</button>
                      )}
                    </div>
                    {openRunId === r.run_id && (
                      <div className="mt-2 border-t border-gray-100 pt-2">
                        {!openRun ? <p className="text-xs text-gray-400">Loading…</p> : (
                          <ol className="space-y-2">
                            {openRun.steps.map((s) => (
                              <li key={s.id} className="text-xs">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-gray-400">{s.id}</span>
                                  <span className="font-medium text-gray-800">{s.skill}</span>
                                  <span className={`px-1.5 py-0.5 rounded ${statusColor(s.status)}`}>{s.status}</span>
                                </div>
                                {s.error && <p className="text-red-600 mt-0.5">{s.error}</p>}
                                <FormattedOutputs skill={s.skill} outputs={s.outputs} />
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "actions" && (
        <div className="border border-gray-200 rounded-lg bg-white overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500"><tr>
              <th className="text-left px-2 py-1">type</th><th className="text-left px-2 py-1">description</th>
              <th className="text-left px-2 py-1">priority</th><th className="text-left px-2 py-1">status</th>
            </tr></thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.action_id} className="border-t border-gray-100">
                  <td className="px-2 py-1 font-mono">{a.action_type}</td>
                  <td className="px-2 py-1">{a.description}</td>
                  <td className="px-2 py-1">{a.priority}</td>
                  <td className="px-2 py-1"><span className={`px-1.5 py-0.5 rounded ${statusColor(a.status)}`}>{a.status}</span></td>
                </tr>
              ))}
              {!actions.length && <tr><td colSpan={4} className="px-2 py-3 text-center text-gray-400">No actions yet — run a workflow that creates actions.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === "entities" && (
        <div className="border border-gray-200 rounded-lg bg-white p-3">
          {!graph || !graph.nodes.length ? (
            <p className="text-sm text-gray-400">No entities yet.</p>
          ) : (
            <>
              <p className="text-xs text-gray-500 mb-2">{graph.nodes.length} entities · {graph.edges.length} relationships</p>
              <div className="flex flex-wrap gap-1">
                {graph.nodes.map((n) => (
                  <span key={n.id} className="text-xs bg-gray-100 rounded px-2 py-0.5">
                    <span className="text-gray-400">{n.type}:</span> {n.label}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
