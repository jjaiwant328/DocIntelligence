"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

export interface DocSet {
  id: string;
  domain_id: string;
  name: string;
  kind: "pinned" | "query";
  filter_json: { source_ids?: string[]; doc_types?: string[]; text?: string };
}

interface SetDoc {
  external_document_id: string;
  name: string;
  web_url: string;
  mime_type: string;
  doc_type: string;
  status: string;
}

export default function DocSetsPanel({ domain }: { domain: DomainInfo }) {
  const [sets, setSets] = useState<DocSet[]>([]);
  const [active, setActive] = useState<DocSet | null>(null);
  const [docs, setDocs] = useState<SetDoc[]>([]);
  const [msg, setMsg] = useState("");

  const [name, setName] = useState("");
  const [kind, setKind] = useState<"pinned" | "query">("pinned");
  const [fSource, setFSource] = useState("");
  const [fTypes, setFTypes] = useState("");
  const [fText, setFText] = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await apiCall<{ doc_sets: DocSet[] }>(
        `/api/doc-sets?domain_id=${encodeURIComponent(domain.domain_id)}`
      );
      setSets(r.doc_sets ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }, [domain.domain_id]);

  useEffect(() => {
    refresh();
    setActive(null);
  }, [refresh]);

  const openDocs = async (s: DocSet) => {
    setActive(s);
    try {
      const r = await apiCall<{ documents: SetDoc[] }>(`/api/doc-sets/${s.id}/docs`);
      setDocs(r.documents ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const create = async () => {
    if (!name.trim()) return;
    const filter_json =
      kind === "query"
        ? {
            source_ids: fSource.split(",").map(s => s.trim()).filter(Boolean),
            doc_types: fTypes.split(",").map(s => s.trim()).filter(Boolean),
            text: fText.trim(),
          }
        : {};
    try {
      await apiCall("/api/doc-sets", {
        method: "POST",
        body: JSON.stringify({ domain_id: domain.domain_id, name: name.trim(), kind, filter_json }),
      });
      setName(""); setFSource(""); setFTypes(""); setFText("");
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (id: string) => {
    try {
      await apiCall(`/api/doc-sets/${id}`, { method: "DELETE" });
      if (active?.id === id) { setActive(null); setDocs([]); }
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const unpin = async (docId: string) => {
    if (!active) return;
    try {
      await apiCall(`/api/doc-sets/${active.id}/pin/${encodeURIComponent(docId)}`, { method: "DELETE" });
      openDocs(active);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h2 className="text-lg font-semibold text-gray-800 mb-1">Doc-Sets</h2>
      <p className="text-sm text-gray-500 mb-4">
        Assemble document sets for a project or research question. Pinned sets hold
        hand-picked docs; query sets stay live as new docs arrive.
      </p>

      {msg && <div className="text-sm text-red-600 mb-3">{msg}</div>}

      {/* Create form */}
      <div className="border border-gray-200 rounded-lg p-4 mb-6 bg-white">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Set name"
            className="text-sm border border-gray-300 rounded px-3 py-1.5 w-56"
          />
          <select
            value={kind}
            onChange={e => setKind(e.target.value as "pinned" | "query")}
            className="text-sm border border-gray-300 rounded px-2 py-1.5"
          >
            <option value="pinned">Pinned</option>
            <option value="query">Query-defined</option>
          </select>
          <button
            onClick={create}
            disabled={!name.trim()}
            className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50"
          >
            + Create set
          </button>
        </div>
        {kind === "query" && (
          <div className="flex flex-wrap gap-2">
            <input
              value={fSource}
              onChange={e => setFSource(e.target.value)}
              placeholder="source_ids (csv, e.g. gdrive_managed,uc_volume)"
              className="text-xs border border-gray-300 rounded px-2 py-1 flex-1 min-w-52"
            />
            <input
              value={fTypes}
              onChange={e => setFTypes(e.target.value)}
              placeholder="mime types (csv)"
              className="text-xs border border-gray-300 rounded px-2 py-1 w-40"
            />
            <input
              value={fText}
              onChange={e => setFText(e.target.value)}
              placeholder="text in name/path"
              className="text-xs border border-gray-300 rounded px-2 py-1 w-40"
            />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Set list */}
        <div className="space-y-2">
          {sets.map(s => (
            <div
              key={s.id}
              className={`border rounded p-3 cursor-pointer ${active?.id === s.id ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white"}`}
              onClick={() => openDocs(s)}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-800">{s.name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.kind === "pinned" ? "bg-purple-100 text-purple-700" : "bg-teal-100 text-teal-700"}`}>
                  {s.kind}
                </span>
                <button
                  onClick={e => { e.stopPropagation(); remove(s.id); }}
                  className="ml-auto text-xs text-gray-400 hover:text-red-600"
                  title="Delete set"
                >
                  🗑
                </button>
              </div>
            </div>
          ))}
          {sets.length === 0 && <p className="text-sm text-gray-400">No sets yet — create one above.</p>}
        </div>

        {/* Members */}
        <div className="md:col-span-2">
          {active && (
            <div className="border border-gray-200 rounded-lg bg-white p-4">
              <h3 className="text-sm font-semibold text-gray-800 mb-2">
                {active.name} — {docs.length} doc(s)
              </h3>
              <div className="space-y-1">
                {docs.map(d => (
                  <div key={d.external_document_id} className="flex items-center gap-2 text-xs border-b border-gray-100 py-1">
                    <span className="font-mono text-gray-700 truncate">{d.name}</span>
                    {d.doc_type && (
                      <span className="px-1 py-0.5 bg-indigo-100 text-indigo-700 rounded">{d.doc_type}</span>
                    )}
                    {d.web_url && (
                      <a href={d.web_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline ml-auto">
                        open ↗
                      </a>
                    )}
                    {active.kind === "pinned" && (
                      <button onClick={() => unpin(d.external_document_id)} className="text-gray-400 hover:text-red-600" title="Unpin">
                        ✕
                      </button>
                    )}
                  </div>
                ))}
                {docs.length === 0 && <p className="text-xs text-gray-400">No documents in this set.</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
