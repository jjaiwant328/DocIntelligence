"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

interface ExecRow {
  execution_id: string; skill_id: string; status: string;
  workflow_id?: string; work_object_id?: string; evidence_count?: number;
  start_time?: string; error?: string;
}
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
  const overlay = (domain?.domain_id ?? "compliance") === "supply_chain" ? "supply_chain" : "compliance";
  const platformDomain = overlayToPlatform(overlay);

  const [rows, setRows] = useState<ExecRow[]>([]);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [graph, setGraph] = useState<{ nodes: OntNode[]; edges: OntEdge[] } | null>(null);
  const [tab, setTab] = useState<"runs" | "actions" | "entities">("runs");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    apiCall<{ executions: ExecRow[] }>("/api/docintel/skill-executions?limit=100")
      .then((r) => setRows(r.executions || [])).catch((e) => setError(String(e)));
    apiCall<{ actions: ActionRow[] }>(`/api/docintel/action-log?domain_id=${platformDomain}`)
      .then((r) => setActions(r.actions || [])).catch(() => setActions([]));
    apiCall<{ nodes: OntNode[]; edges: OntEdge[] }>(`/api/docintel/ontology-graph?domain_id=${platformDomain}`)
      .then((r) => setGraph({ nodes: r.nodes || [], edges: r.edges || [] })).catch(() => setGraph(null));
  }
  useEffect(refresh, [platformDomain]);

  // group executions by workflow_id (single-skill runs grouped under "—")
  const groups: Record<string, ExecRow[]> = {};
  rows.forEach((r) => {
    const k = r.workflow_id || "(single skills)";
    (groups[k] = groups[k] || []).push(r);
  });

  return (
    <div className="px-4 py-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">
          Runs and their outputs for <span className="font-semibold text-gray-700">{domain?.name ?? overlay}</span> —
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
        <div className="space-y-4">
          {Object.keys(groups).length === 0 && <p className="text-sm text-gray-400">No runs yet.</p>}
          {Object.entries(groups).map(([wf, steps]) => (
            <div key={wf} className="border border-gray-200 rounded-lg bg-white">
              <div className="px-3 py-2 border-b border-gray-100 flex items-center gap-2">
                <span className="text-sm font-medium text-gray-800">{wf}</span>
                <span className="text-xs text-gray-400">{steps.length} step(s)</span>
              </div>
              <ul className="divide-y divide-gray-50">
                {steps.map((s) => (
                  <li key={s.execution_id} className="px-3 py-1.5 flex items-center gap-3 text-xs">
                    <span className="font-mono">{s.skill_id}</span>
                    <span className={`px-1.5 py-0.5 rounded ${statusColor(s.status)}`}>{s.status}</span>
                    <span className="text-gray-400">{(s.evidence_count ?? 0)} ev</span>
                    <span className="ml-auto text-gray-400">{String(s.start_time || "").slice(0, 19)}</span>
                  </li>
                ))}
              </ul>
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
