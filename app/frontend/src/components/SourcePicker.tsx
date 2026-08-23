"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";

interface SourceMeta { id: string; name: string; mode: string; connected: boolean; note?: string; auth_path?: string | null }
interface SourceDoc { doc_ref: string; name: string; mime_type?: string; size?: number; folder?: string; doc_type_hint?: string }
interface ImportResult { landed: string[]; count: number; volume_path?: string; pipeline_run_id?: number; pipeline_error?: string; errors?: { doc_ref: string; error: string }[] }

/**
 * Import documents from an external source (Google Drive) via the MCP sources
 * server: browse → select → import. Imported files land in the domain's UC
 * Volume and (by default) kick off the existing parse/skill pipeline.
 */
export function SourcePicker({ domainId }: { domainId: string }) {
  const { project } = useDomain();
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [sources, setSources] = useState<SourceMeta[]>([]);
  const [source, setSource] = useState<string>("gdrive");
  const [docs, setDocs] = useState<SourceDoc[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  useEffect(() => {
    apiCall<{ configured: boolean; sources: SourceMeta[]; error?: string }>("/api/docintel/sources")
      .then((r) => { setConfigured(r.configured); setSources(r.sources || []); if (r.sources?.[0]) setSource(r.sources[0].id); })
      .catch(() => setConfigured(false));
  }, []);

  function browse() {
    setLoading(true); setMsg(null);
    apiCall<{ items: SourceDoc[] }>(`/api/docintel/sources/${source}/documents?query=${encodeURIComponent(query)}`)
      .then((r) => { setDocs(r.items || []); setOpen(true); })
      .catch((e) => setMsg(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  async function connect() {
    try {
      const r = await apiCall<{ auth_url: string }>(`/api/docintel/sources/${source}/auth-url`);
      if (r.auth_url) window.open(r.auth_url, "_blank");
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  const selected = docs.filter((d) => checked[d.doc_ref]).map((d) => d.doc_ref);

  async function importDocs() {
    if (!selected.length) return;
    setLoading(true); setMsg(null); setResult(null);
    try {
      const r = await apiCall<ImportResult>("/api/docintel/sources/import", {
        method: "POST",
        body: JSON.stringify({
          source, doc_refs: selected, domain_id: domainId,
          project_id: project?.project_id || "", trigger_pipeline: true,
        }),
      });
      setResult(r);
      setMsg(`Imported ${r.count} document(s) to the volume${r.pipeline_run_id ? " — processing started." : "."}`);
      setChecked({});
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }

  if (configured === false) return null;   // sources server not wired — hide the panel

  const cur = sources.find((s) => s.id === source);

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 mb-4 mx-4 mt-4">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-gray-800">📥 Import from a source</span>
        <select className="text-xs border rounded px-2 py-1" value={source} onChange={(e) => { setSource(e.target.value); setOpen(false); setDocs([]); }}>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {cur && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded-full ${cur.mode === "real" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
            {cur.mode === "real" ? (cur.connected ? "✓ Live" : "○ Not connected") : "Demo data"}
          </span>
        )}
        {cur && cur.mode === "real" && !cur.connected && (
          <button onClick={connect} className="text-xs text-blue-600 underline">Connect {cur.name}</button>
        )}
        <input className="text-xs border rounded px-2 py-1 w-40" placeholder="search…" value={query}
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && browse()} />
        <button onClick={browse} disabled={loading} className="text-xs bg-gray-800 text-white rounded px-3 py-1 disabled:opacity-50">
          {loading ? "…" : open ? "Refresh" : "Browse"}
        </button>
        {open && (
          <button onClick={importDocs} disabled={loading || !selected.length}
            className="text-xs bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-40">
            Import {selected.length || ""} to {project?.name ? `📁 ${project.name}` : "volume"}
          </button>
        )}
      </div>
      {cur?.note && !open && <p className="text-[11px] text-gray-400 mb-1">{cur.note}</p>}
      {msg && <div className="mb-2 text-xs text-gray-700 bg-gray-50 border rounded p-1.5">{msg}</div>}
      {result?.pipeline_error && <div className="mb-2 text-xs text-red-600">Pipeline: {result.pipeline_error}</div>}

      {open && (
        <div className="max-h-64 overflow-y-auto border rounded">
          {docs.length === 0 ? (
            <p className="text-xs text-gray-400 p-3">No documents found.</p>
          ) : docs.map((d) => (
            <label key={d.doc_ref} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-gray-50 last:border-0 hover:bg-gray-50">
              <input type="checkbox" checked={!!checked[d.doc_ref]}
                onChange={(e) => setChecked((c) => ({ ...c, [d.doc_ref]: e.target.checked }))} />
              <span className="truncate">{d.name}</span>
              {d.folder && <span className="text-gray-400">· {d.folder}</span>}
              {d.doc_type_hint && <span className="ml-auto text-gray-400">{d.doc_type_hint}</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
