"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

interface SkillMeta {
  id: string; category: string; enabled: boolean;
  description?: string; adapter?: string;
  inputs?: Record<string, { type?: string; required?: boolean }>;
  outputs?: Record<string, unknown>;
  side_effects?: Record<string, unknown>;
}
interface ParsedDoc { doc_id: string; doc_type?: string; }
interface Evidence { document_id: string; source_text?: string; method?: string; }
interface SkillResult { status: string; outputs: Record<string, unknown>; evidence: Evidence[]; error?: string | null; }

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];

function overlayDomain(domainId: string): string {
  return domainId === "supply_chain" ? "supply_chain" : "compliance";
}
function statusColor(s: string): string {
  if (["ok", "satisfied", "completed"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "error") return "bg-red-100 text-red-800";
  if (s === "gap") return "bg-orange-100 text-orange-800";
  if (s === "insufficient_evidence") return "bg-gray-200 text-gray-700";
  return "bg-blue-100 text-blue-800";
}

export default function SkillsTab({ domain }: { domain?: DomainInfo }) {
  const domainId = overlayDomain(domain?.domain_id ?? "compliance");
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [docs, setDocs] = useState<ParsedDoc[]>([]);
  const [selected, setSelected] = useState<SkillMeta | null>(null);
  const [mode, setMode] = useState<"docs" | "manual">("docs");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [inputsText, setInputsText] = useState("{}");
  const [result, setResult] = useState<SkillResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiCall<{ skills: SkillMeta[] }>("/api/docintel/skills")
      .then((r) => setSkills(r.skills)).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    apiCall<{ documents: ParsedDoc[] }>(`/api/docintel/parsed-documents?domain_id=${domainId}`)
      .then((r) => {
        setDocs(r.documents || []);
        // default: all selected
        const all: Record<string, boolean> = {};
        (r.documents || []).forEach((d) => { all[d.doc_id] = true; });
        setChecked(all);
      })
      .catch(() => setDocs([]));
  }, [domainId]);

  function pick(s: SkillMeta) {
    setSelected(s); setResult(null); setError(null);
    const scaffold: Record<string, unknown> = {};
    Object.entries(s.inputs ?? {}).forEach(([k, spec]) => {
      if (spec.required) scaffold[k] = spec.type === "array" ? [] : "";
    });
    setInputsText(JSON.stringify(scaffold, null, 2));
  }

  const selectedDocIds = docs.filter((d) => checked[d.doc_id]).map((d) => d.doc_id);

  async function run() {
    if (!selected) return;
    setLoading(true); setError(null);
    try {
      const body: Record<string, unknown> = { skill: selected.id, domain_id: domainId };
      if (mode === "docs") body.doc_ids = selectedDocIds;
      else body.inputs = JSON.parse(inputsText || "{}");
      const r = await apiCall<SkillResult>("/api/docintel/skill-invoke", {
        method: "POST", body: JSON.stringify(body),
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  const byCat = CATEGORY_ORDER
    .map((cat) => ({ cat, items: skills.filter((s) => s.category === cat) }))
    .filter((g) => g.items.length);

  return (
    <div className="px-4 py-4">
      <p className="text-sm text-gray-500 mb-3">
        Apply a skill to <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>&apos;s
        parsed documents. Inputs are populated automatically from the documents you select.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* palette */}
        <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[70vh] overflow-y-auto">
          {error && <div className="mb-2 text-xs text-red-600">{error}</div>}
          {byCat.map((g) => (
            <div key={g.cat} className="mb-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{g.cat}</p>
              {g.items.map((s) => (
                <button key={s.id} onClick={() => pick(s)}
                  className={`block w-full text-left text-sm px-2 py-1 rounded ${selected?.id === s.id ? "bg-blue-100 text-blue-800" : "hover:bg-gray-50"}`}>
                  {s.id}
                  {s.side_effects?.creates_actions ? <span className="ml-1 text-[10px] text-amber-600">✎</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* apply-to + run */}
        <div className="md:col-span-2">
          {!selected ? (
            <p className="text-sm text-gray-400">Select a skill to apply.</p>
          ) : (
            <div className="border border-gray-200 rounded-lg bg-white p-4">
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold text-gray-800">{selected.id}</h3>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{selected.adapter}</span>
              </div>
              <p className="text-sm text-gray-600 mt-1">{selected.description}</p>

              {/* mode toggle */}
              <div className="mt-3 flex gap-4 text-sm">
                <label className="flex items-center gap-1">
                  <input type="radio" checked={mode === "docs"} onChange={() => setMode("docs")} />
                  Parsed documents (auto)
                </label>
                <label className="flex items-center gap-1">
                  <input type="radio" checked={mode === "manual"} onChange={() => setMode("manual")} />
                  Manual input
                </label>
              </div>

              {mode === "docs" ? (
                <div className="mt-3 border rounded max-h-56 overflow-y-auto">
                  {docs.length === 0 ? (
                    <p className="text-xs text-gray-400 p-3">No parsed documents in this subject area yet.</p>
                  ) : docs.map((d) => (
                    <label key={d.doc_id} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-gray-50 last:border-0">
                      <input type="checkbox" checked={!!checked[d.doc_id]}
                        onChange={(e) => setChecked((c) => ({ ...c, [d.doc_id]: e.target.checked }))} />
                      <span className="font-mono">{d.doc_id}</span>
                      {d.doc_type && <span className="text-gray-400">· {d.doc_type}</span>}
                    </label>
                  ))}
                </div>
              ) : (
                <textarea className="mt-3 w-full h-32 border rounded p-2 font-mono text-xs"
                  value={inputsText} onChange={(e) => setInputsText(e.target.value)} />
              )}

              <button onClick={run} disabled={loading || (mode === "docs" && !selectedDocIds.length)}
                className="mt-3 bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50">
                {loading ? "Running…" : mode === "docs" ? `Run skill on ${selectedDocIds.length} document(s)` : "Run skill"}
              </button>

              {result && (
                <div className="mt-4">
                  <span className={`text-xs px-2 py-0.5 rounded ${statusColor(result.status)}`}>{result.status}</span>
                  {result.error && <p className="text-xs text-red-600 mt-1">{result.error}</p>}
                  <pre className="mt-2 text-xs bg-gray-50 rounded p-2 overflow-x-auto">{JSON.stringify(result.outputs, null, 2)}</pre>
                  {result.evidence?.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs font-semibold text-gray-500">Evidence ({result.evidence.length})</p>
                      <ul className="mt-1 space-y-1">
                        {result.evidence.map((ev, i) => (
                          <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2">
                            <span className="font-mono">{ev.document_id}</span>{ev.method ? ` · ${ev.method}` : ""}
                            {ev.source_text ? ` — ${ev.source_text.slice(0, 140)}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
