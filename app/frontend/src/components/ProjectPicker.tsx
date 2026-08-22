"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { ProjectInfo } from "@/context/DomainContext";

/** Map the shell's domain id to the overlay id the backend routes expect. */
function overlayDomain(d: string): string {
  return d === "supply_chain" ? "supply_chain" : "compliance";
}

export function ProjectPicker({
  domainId, project, onChange,
}: {
  domainId: string;
  project: ProjectInfo | null;
  onChange: (p: ProjectInfo | null) => void;
}) {
  const { actingUser, enforceAccess } = useDomain();
  const overlay = overlayDomain(domainId);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  function load() {
    const q = `/api/docintel/projects?domain_id=${overlay}` +
      `&as_user=${encodeURIComponent(actingUser)}&enforce=${enforceAccess}`;
    apiCall<{ projects: ProjectInfo[] }>(q)
      .then((r) => {
        setProjects(r.projects || []);
        // if the current selection is no longer visible under enforcement, clear it
        if (project && !(r.projects || []).some((p) => p.project_id === project.project_id)) {
          onChange(null);
        }
      })
      .catch((e) => setErr(String(e)));
  }
  useEffect(load, [overlay, actingUser, enforceAccess]);   // eslint-disable-line

  async function create() {
    if (!newName.trim()) { setErr("Project name required."); return; }
    setErr(null);
    try {
      // only the name is needed — backend generates the id; creator becomes owner
      const r = await apiCall<{ status?: string; error?: string; project_id?: string; owner?: string }>("/api/docintel/projects", {
        method: "POST",
        body: JSON.stringify({ domain_id: overlay, name: newName.trim(), owner: actingUser }),
      });
      if (r.error || !r.project_id) { setErr(r.error || "create failed"); return; }
      const created: ProjectInfo = { project_id: r.project_id, name: newName.trim(), owner: actingUser, collaborators: [] };
      setCreating(false); setNewName("");
      load();
      onChange(created);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }

  async function del() {
    if (!project?.project_id) return;
    if (!window.confirm(`Delete project "${project.name || project.project_id}"? This removes the project and its document tags.`)) return;
    setErr(null);
    try {
      await apiCall(`/api/docintel/projects/${encodeURIComponent(project.project_id)}?domain_id=${overlay}`,
        { method: "DELETE" });
      onChange(null);
      load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }

  const sel = projects.find((p) => p.project_id === project?.project_id) || project;

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] text-gray-400">📁 Project</span>
      <select
        className="text-xs border rounded px-2 py-1 max-w-[220px]"
        value={project?.project_id ?? ""}
        onChange={(e) => {
          const p = projects.find((x) => x.project_id === e.target.value) ?? null;
          onChange(p);
        }}
      >
        <option value="">All documents</option>
        {projects.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.name || p.project_id}
          </option>
        ))}
      </select>
      {sel?.owner && (
        <span className="text-[10px] text-gray-400" title={`Owner: ${sel.owner}${sel.collaborators?.length ? ` · Collaborators: ${sel.collaborators.join(", ")}` : ""}`}>
          👑 {sel.owner}{sel.collaborators?.length ? ` +${sel.collaborators.length}` : ""}
        </span>
      )}
      {project?.project_id && (!sel?.owner || sel.owner === actingUser) && (
        <button onClick={del} title="Delete this project"
          className="text-[11px] text-red-400 hover:text-red-600 px-1">🗑</button>
      )}
      {creating ? (
        <span className="flex items-center gap-1">
          <input className="text-xs border rounded px-1.5 py-1 w-40" placeholder="Project name"
            autoFocus value={newName} onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
          <button onClick={create} className="text-xs bg-blue-600 text-white rounded px-2 py-1">Add</button>
          <button onClick={() => { setCreating(false); setErr(null); }} className="text-xs text-gray-400 px-1">✕</button>
        </span>
      ) : (
        <button onClick={() => setCreating(true)} title="New project/case"
          className="text-xs text-gray-400 hover:text-gray-700 px-1">+ New</button>
      )}
      {err && <span className="text-[10px] text-red-500">{err}</span>}
    </div>
  );
}
