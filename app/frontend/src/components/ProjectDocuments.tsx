"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain, DEMO_USERS } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";

interface DocRow { doc_id: string; doc_type?: string; in_project?: boolean }

/**
 * Assemble a project's document set: shows every parsed document in the subject
 * area, with the ones already in the selected project checked. Add/remove tags
 * documents via platform.document_project_tags — the same set Skills, Workflows,
 * Executions and Copilot read when a project is selected.
 */
export function ProjectDocuments({ domain }: { domain?: DomainInfo }) {
  const { project, setProject, actingUser } = useDomain();
  const domainId = domain?.domain_id ?? "compliance_due_diligence";
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    const q = `/api/docintel/all-documents?domain_id=${domainId}` +
      (project?.project_id ? `&project_id=${encodeURIComponent(project.project_id)}` : "");
    apiCall<{ documents: DocRow[] }>(q)
      .then((r) => {
        setDocs(r.documents || []);
        const init: Record<string, boolean> = {};
        (r.documents || []).forEach((d) => { init[d.doc_id] = !!d.in_project; });
        setChecked(init);
      })
      .catch((e) => setMsg(String(e)));
  }
  useEffect(load, [domainId, project?.project_id]);

  if (!project?.project_id) {
    return (
      <div className="border border-amber-200 bg-amber-50 rounded-lg p-3 text-sm text-amber-800">
        Pick a <span className="font-semibold">Project</span> in the header to assemble its document set.
        The documents you add here become the working set for Skills, Workflows, Executions and Copilot.
      </div>
    );
  }

  const visible = docs.filter((d) => d.doc_id.toLowerCase().includes(filter.toLowerCase()));
  const inCount = docs.filter((d) => checked[d.doc_id]).length;
  // docs whose checkbox state differs from their persisted membership
  const toAdd = docs.filter((d) => checked[d.doc_id] && !d.in_project).map((d) => d.doc_id);
  const toRemove = docs.filter((d) => !checked[d.doc_id] && d.in_project).map((d) => d.doc_id);
  const dirty = toAdd.length + toRemove.length;

  async function apply() {
    setLoading(true); setMsg(null);
    try {
      if (toAdd.length) {
        await apiCall("/api/docintel/project-documents", {
          method: "POST",
          body: JSON.stringify({ domain_id: domainId, project_id: project!.project_id, doc_ids: toAdd }),
        });
      }
      if (toRemove.length) {
        await apiCall("/api/docintel/project-documents", {
          method: "DELETE",
          body: JSON.stringify({ domain_id: domainId, project_id: project!.project_id, doc_ids: toRemove }),
        });
      }
      setMsg(`Updated — ${toAdd.length} added, ${toRemove.length} removed.`);
      load();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }

  const isOwner = !project?.owner || project.owner === actingUser;
  async function saveMembers(owner: string, collaborators: string[]) {
    if (!project?.project_id) return;
    try {
      await apiCall(`/api/docintel/projects/${encodeURIComponent(project.project_id)}/members`, {
        method: "PATCH",
        body: JSON.stringify({ domain_id: domainId, owner, collaborators }),
      });
      setProject({ ...project, owner, collaborators });
      setMsg("Ownership / collaborators updated.");
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 mb-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm text-gray-700">
          Documents for <span className="font-semibold">📁 {project.name || project.project_id}</span>
          <span className="text-gray-400 text-xs"> · {inCount} of {docs.length} in project</span>
        </p>
        <div className="flex items-center gap-2">
          <input className="text-xs border rounded px-2 py-1 w-40" placeholder="filter…"
            value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button onClick={() => setChecked(Object.fromEntries(docs.map((d) => [d.doc_id, true])))}
            className="text-xs text-blue-600">Select all</button>
          <button onClick={() => setChecked({})} className="text-xs text-gray-400">Clear</button>
          <button onClick={apply} disabled={loading || !dirty}
            className="text-xs bg-blue-600 text-white rounded px-3 py-1.5 disabled:opacity-40">
            {loading ? "Saving…" : dirty ? `Apply (${dirty})` : "No changes"}
          </button>
        </div>
      </div>
      {/* Owner + collaborators (demo identity, lightweight) */}
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs bg-gray-50 border border-gray-100 rounded p-2">
        <span className="text-gray-500">👑 Owner:</span>
        {isOwner ? (
          <select value={project.owner || actingUser}
            onChange={(e) => saveMembers(e.target.value, project.collaborators || [])}
            className="text-xs border rounded px-1.5 py-0.5">
            {DEMO_USERS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        ) : <span className="font-medium text-gray-700">{project.owner}</span>}
        <span className="text-gray-500 ml-2">Collaborators:</span>
        <span className="flex flex-wrap gap-1">
          {DEMO_USERS.filter((u) => u !== (project.owner || actingUser)).map((u) => {
            const on = (project.collaborators || []).includes(u);
            return (
              <button key={u} disabled={!isOwner}
                onClick={() => {
                  const cur = project.collaborators || [];
                  const next = on ? cur.filter((c) => c !== u) : [...cur, u];
                  saveMembers(project.owner || actingUser, next);
                }}
                className={`px-1.5 py-0.5 rounded border ${on ? "bg-blue-100 text-blue-700 border-blue-200" : "bg-white text-gray-500 border-gray-200"} disabled:opacity-50`}>
                {on ? "✓ " : "+ "}{u}
              </button>
            );
          })}
        </span>
        {!isOwner && <span className="text-gray-400">(only the owner can change members)</span>}
      </div>
      {msg && <div className="mb-2 text-xs text-gray-600 bg-gray-50 border rounded p-1.5">{msg}</div>}
      <div className="max-h-72 overflow-y-auto border rounded">
        {visible.length === 0 ? (
          <p className="text-xs text-gray-400 p-3">No documents.</p>
        ) : visible.map((d) => (
          <label key={d.doc_id} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-gray-50 last:border-0 hover:bg-gray-50">
            <input type="checkbox" checked={!!checked[d.doc_id]}
              onChange={(e) => setChecked((c) => ({ ...c, [d.doc_id]: e.target.checked }))} />
            <span className="font-mono truncate">{d.doc_id}</span>
            {d.doc_type && <span className="ml-auto text-gray-400">{d.doc_type}</span>}
          </label>
        ))}
      </div>
    </div>
  );
}
