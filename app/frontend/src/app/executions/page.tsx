"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";
import { FormattedOutputs, RunReport } from "@/components/FormattedOutputs";

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
interface CheckRow { check: string; count: number; high: number; medium: number; low: number; impact: number; }
interface Coverage {
  documents: { total: number; by_type: { doc_type: string; count: number }[] };
  findings: { total: number; by_check: CheckRow[] };
  evidence: { quotes: number; docs: number };
  runs_considered: number;
}

function statusColor(s: string): string {
  if (["ok", "completed", "satisfied", "CLOSED", "ASSIGNED"].includes(s)) return "bg-green-100 text-green-800";
  if (["error", "failed"].includes(s)) return "bg-red-100 text-red-800";
  if (s === "DRAFT") return "bg-amber-100 text-amber-800";
  if (s === "ESCALATED") return "bg-red-100 text-red-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  return "bg-blue-100 text-blue-800";
}

function prioColor(p: string): string {
  const s = (p || "").toUpperCase();
  if (s === "HIGH" || s === "CRITICAL") return "bg-red-100 text-red-700";
  if (s === "LOW") return "bg-gray-100 text-gray-600";
  return "bg-amber-100 text-amber-800";
}

function titleCase(s: string): string {
  return (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function ExecutionsTab({ domain }: { domain?: DomainInfo }) {
  const { project } = useDomain();
  // P4: one canonical use_case_id — no overlay/platform split.
  const domainId = domain?.domain_id ?? "compliance_due_diligence";

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [graph, setGraph] = useState<{ nodes: OntNode[]; edges: OntEdge[] } | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [tab, setTab] = useState<"runs" | "actions" | "entities">("runs");
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<FullRun | null>(null);
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [showSteps, setShowSteps] = useState(false);
  const [busyRun, setBusyRun] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function patchAction(actionId: string, status: string) {
    setBusyAction(actionId);
    try {
      await apiCall(`/api/docintel/action-log/${encodeURIComponent(actionId)}`, {
        method: "PATCH",
        body: JSON.stringify({ status, domain_id: domainId, logged_by: status === "ASSIGNED" ? "me" : undefined }),
      });
      setActions((as) => as.map((a) => (a.action_id === actionId ? { ...a, status } : a)));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusyAction(null); }
  }

  async function reopen(runId: string) {
    setOpenRunId(runId); setOpenRun(null); setShowSteps(false);
    try {
      const r = await apiCall<{ run: FullRun | null; error?: string }>(`/api/docintel/workflow-run/${encodeURIComponent(runId)}`);
      setOpenRun(r.run);
    } catch { setOpenRun(null); }
  }

  async function del(runId: string) {
    if (!confirm("Delete this execution? This can't be undone.")) return;
    setBusyRun(runId);
    try {
      await apiCall(`/api/docintel/workflow-run/${encodeURIComponent(runId)}`, { method: "DELETE" });
      if (openRunId === runId) { setOpenRunId(null); setOpenRun(null); }
      setRuns((rs) => rs.filter((r) => r.run_id !== runId));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusyRun(null); }
  }

  async function rename(runId: string, current?: string) {
    const label = prompt("Name this execution:", current || "");
    if (label == null) return;
    setBusyRun(runId);
    try {
      await apiCall(`/api/docintel/workflow-run/${encodeURIComponent(runId)}`, {
        method: "PATCH", body: JSON.stringify({ label }),
      });
      setRuns((rs) => rs.map((r) => (r.run_id === runId ? { ...r, label } : r)));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusyRun(null); }
  }

  function refresh() {
    const pid = project?.project_id;
    const projQ = pid ? `&project_id=${encodeURIComponent(pid)}` : "";
    apiCall<{ runs: RunRow[] }>(`/api/docintel/workflow-runs?domain_id=${domainId}${projQ}`)
      .then((r) => setRuns(r.runs || [])).catch(() => setRuns([]));
    // Actions are tied to a project via action_log.incident_ref = project_id
    // (set by the create_action skill). Scope to the selected project.
    const actQ = pid ? `&incident_ref=${encodeURIComponent(pid)}` : "";
    apiCall<{ actions: ActionRow[] }>(`/api/docintel/action-log?domain_id=${domainId}${actQ}`)
      .then((r) => setActions(r.actions || [])).catch(() => setActions([]));
    apiCall<{ nodes: OntNode[]; edges: OntEdge[] }>(`/api/docintel/ontology-graph?domain_id=${domainId}`)
      .then((r) => setGraph({ nodes: r.nodes || [], edges: r.edges || [] })).catch(() => setGraph(null));
    apiCall<Coverage>(`/api/docintel/run-coverage?domain_id=${domainId}${projQ}`)
      .then(setCoverage).catch(() => setCoverage(null));
  }
  useEffect(refresh, [domainId, project?.project_id]);

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
          Runs and their outputs for <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>
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
                      <span className="text-sm font-medium text-gray-800">{r.label || r.template_id}</span>
                      {r.label && <span className="text-gray-400">{r.template_id}</span>}
                      <span className={`px-1.5 py-0.5 rounded ${statusColor(r.status)}`}>{r.status}</span>
                      <span className="text-gray-400">{r.step_count ?? 0} step(s){(r.error_count ?? 0) > 0 ? ` · ${r.error_count} error(s)` : ""}</span>
                      {r.halted_at && <span className="text-amber-600">halted at {r.halted_at}</span>}
                      <span className="ml-auto text-gray-400">{String(r.created_at || "").slice(0, 19)}</span>
                      {r.saved && (
                        <button onClick={() => (openRunId === r.run_id ? setOpenRunId(null) : reopen(r.run_id))}
                          className="text-blue-600">{openRunId === r.run_id ? "Hide" : "Open"}</button>
                      )}
                      <button onClick={() => rename(r.run_id, r.label)} disabled={busyRun === r.run_id}
                        title="Rename" className="text-gray-400 hover:text-gray-600 disabled:opacity-40">✎</button>
                      <button onClick={() => del(r.run_id)} disabled={busyRun === r.run_id}
                        title="Delete" className="text-gray-400 hover:text-red-600 disabled:opacity-40">🗑</button>
                    </div>
                    {openRunId === r.run_id && (
                      <div className="mt-2 border-t border-gray-100 pt-2">
                        {!openRun ? <p className="text-xs text-gray-400">Loading…</p> : (
                          <>
                            <RunReport run={openRun} />
                            <button onClick={() => setShowSteps((v) => !v)}
                              className="text-[11px] text-gray-500 hover:text-gray-700">
                              {showSteps ? "▾ Hide step detail" : "▸ Step detail"}
                            </button>
                            {showSteps && (
                              <ol className="space-y-2 mt-2">
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
                          </>
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
        <div>
          {actions.length > 0 && (() => {
            const open = actions.filter((a) => a.status === "DRAFT").length;
            const esc = actions.filter((a) => a.status === "ESCALATED").length;
            const done = actions.filter((a) => a.status === "CLOSED").length;
            return (
              <p className="text-xs text-gray-500 mb-2">
                {actions.length} action(s){open ? ` · ${open} open` : ""}{esc ? ` · ${esc} escalated` : ""}{done ? ` · ${done} resolved` : ""}
              </p>
            );
          })()}
          <div className="border border-gray-200 rounded-lg bg-white overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500"><tr>
                <th className="text-left px-2 py-1.5">type</th><th className="text-left px-2 py-1.5">action</th>
                <th className="text-left px-2 py-1.5">priority</th><th className="text-left px-2 py-1.5">status</th>
                <th className="text-left px-2 py-1.5"></th>
              </tr></thead>
              <tbody>
                {actions.map((a) => {
                  const busy = busyAction === a.action_id;
                  return (
                    <tr key={a.action_id} className="border-t border-gray-100 align-top">
                      <td className="px-2 py-1.5">
                        <span className="font-medium text-blue-700 whitespace-nowrap">{titleCase(a.action_type)}</span>
                      </td>
                      <td className="px-2 py-1.5 text-gray-700">{a.description || <span className="text-gray-400">—</span>}</td>
                      <td className="px-2 py-1.5"><span className={`px-1.5 py-0.5 rounded ${prioColor(a.priority)}`}>{a.priority}</span></td>
                      <td className="px-2 py-1.5"><span className={`px-1.5 py-0.5 rounded ${statusColor(a.status)}`}>{a.status}</span></td>
                      <td className="px-2 py-1.5">
                        <div className="flex gap-1 whitespace-nowrap">
                          {a.status === "DRAFT" && (
                            <button disabled={busy} onClick={() => patchAction(a.action_id, "ASSIGNED")}
                              className="px-1.5 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40">Assign to me</button>
                          )}
                          {(a.status === "DRAFT" || a.status === "ASSIGNED") && (
                            <button disabled={busy} onClick={() => patchAction(a.action_id, "ESCALATED")}
                              className="px-1.5 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40">Escalate</button>
                          )}
                          {(a.status === "ASSIGNED" || a.status === "ESCALATED") && (
                            <button disabled={busy} onClick={() => patchAction(a.action_id, "CLOSED")}
                              className="px-1.5 py-0.5 rounded border border-green-200 text-green-700 hover:bg-green-50 disabled:opacity-40">Resolve</button>
                          )}
                          {a.status === "CLOSED" && <span className="text-green-600">✓ resolved</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!actions.length && <tr><td colSpan={5} className="px-2 py-3 text-center text-gray-400">No actions yet — run a workflow that creates actions.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "entities" && (
        <div className="space-y-3">
          {/* Coverage: documents ingested, findings by check, evidence reach */}
          {coverage && (coverage.documents.total > 0 || coverage.findings.total > 0) && (
            <div className="border border-gray-200 rounded-lg bg-white p-3">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
                    Documents covered ({coverage.documents.total})
                  </div>
                  {coverage.documents.by_type.length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {coverage.documents.by_type.map((d) => (
                        <span key={d.doc_type} className="text-xs bg-gray-100 rounded px-2 py-0.5">
                          {titleCase(d.doc_type)} <span className="font-semibold text-gray-700">{d.count}</span>
                        </span>
                      ))}
                    </div>
                  ) : <p className="text-xs text-gray-400">No documents ingested yet.</p>}
                  <p className="text-[11px] text-gray-400 mt-2">
                    Evidence: {coverage.evidence.quotes} quote(s) across {coverage.evidence.docs} doc(s)
                  </p>
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
                    Findings by check ({coverage.findings.total})
                    {coverage.runs_considered > 0 && <span className="ml-1 font-normal normal-case text-gray-400">· latest of {coverage.runs_considered} workflow(s)</span>}
                  </div>
                  {coverage.findings.by_check.length ? (
                    <ul className="space-y-1">
                      {coverage.findings.by_check.map((c) => (
                        <li key={c.check} className="text-xs flex items-center gap-2">
                          <span className="text-gray-700 flex-1">{titleCase(c.check)}</span>
                          <span className="flex gap-0.5" title={`${c.high} high · ${c.medium} medium · ${c.low} low`}>
                            {Array.from({ length: c.high }).map((_, i) => <span key={`h${i}`} className="text-red-500">●</span>)}
                            {Array.from({ length: c.medium }).map((_, i) => <span key={`m${i}`} className="text-amber-500">●</span>)}
                            {Array.from({ length: c.low }).map((_, i) => <span key={`l${i}`} className="text-gray-400">●</span>)}
                          </span>
                          <span className="font-semibold text-gray-700 w-5 text-right">{c.count}</span>
                          {c.impact > 0 && <span className="text-red-600 w-16 text-right">${c.impact.toLocaleString()}</span>}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-xs text-gray-400">No findings yet — run a reconcile workflow.</p>}
                </div>
              </div>
            </div>
          )}

          {/* Ontology graph, when the domain has one */}
          <div className="border border-gray-200 rounded-lg bg-white p-3">
            {!graph || !graph.nodes.length ? (
              <p className="text-sm text-gray-400">
                {coverage && coverage.documents.total > 0 ? "No entity graph for this domain — coverage shown above." : "No entities yet."}
              </p>
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
        </div>
      )}
    </div>
  );
}
