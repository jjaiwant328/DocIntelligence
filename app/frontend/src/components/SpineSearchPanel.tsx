"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

interface DocSet {
  id: string;
  name: string;
  kind: "pinned" | "query";
}

interface SearchHit {
  doc_id: string;
  doc_type: string;
  source_file: string;
  chunk_to_retrieve: string;
  score: number;
  judge_score?: number;
  source?: { provider: string; url: string };
}

interface Validation {
  field_confidence?: Record<string, number>;
  type_check?: { extracted_type: string; judge_choice: string; confidence: number; match: boolean };
  error?: string;
}

interface Evidence {
  document: { doc_id: string; doc_type: string; source_file: string };
  extracted_fields: { field_name: string; field_value: string }[];
  source_chunks: { chunk_position: number; source_text: string }[];
  validation?: Validation;
}

export default function SpineSearchPanel({ domain }: { domain: DomainInfo }) {
  const [question, setQuestion] = useState("");
  const [rerank, setRerank] = useState(true);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [docSets, setDocSets] = useState<DocSet[]>([]);
  const [docSetId, setDocSetId] = useState("");

  useEffect(() => {
    setDocSetId("");
    apiCall<{ doc_sets: DocSet[] }>(`/api/doc-sets?domain_id=${encodeURIComponent(domain.domain_id)}`)
      .then(r => setDocSets(r.doc_sets ?? []))
      .catch(() => setDocSets([]));
  }, [domain.domain_id]);

  const pinHit = async (docId: string) => {
    const s = docSets.find(x => x.id === docSetId);
    if (!s || s.kind !== "pinned") return;
    try {
      await apiCall(`/api/doc-sets/${s.id}/pin`, {
        method: "POST",
        body: JSON.stringify({ doc_ids: [docId] }),
      });
    } catch { /* silent — pin is opportunistic */ }
  };

  const runSearch = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setEvidence(null);
    try {
      const out = await apiCall<{ results: SearchHit[] }>("/api/spine/search", {
        method: "POST",
        body: JSON.stringify({ question, domain_id: domain.domain_id, k: 5, rerank, doc_set_id: docSetId }),
      });
      setHits(out.results ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setHits([]);
    } finally {
      setLoading(false);
    }
  };

  const openEvidence = async (docId: string, validate = false) => {
    if (validate) setValidating(true); else setEvidenceLoading(true);
    try {
      const ev = await apiCall<Evidence>(
        `/api/spine/evidence?doc_id=${encodeURIComponent(docId)}&domain_id=${encodeURIComponent(domain.domain_id)}${validate ? "&validate=true" : ""}`
      );
      setEvidence(ev);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEvidenceLoading(false);
      setValidating(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h2 className="text-lg font-semibold text-gray-800 mb-1">Search &amp; Evidence</h2>
      <p className="text-sm text-gray-500 mb-4">
        Endpoint-free semantic search over the {domain.name} corpus, reranked by the OpenJev
        judge. Every hit drills down to extracted fields and source chunks.
      </p>

      <div className="flex gap-2 mb-1">
        <input
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm"
          placeholder="Ask something about the corpus…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
        />
        <button
          onClick={runSearch}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </div>
      <div className="flex items-center gap-3 mb-4">
        <label className="flex items-center gap-1 text-xs text-gray-500">
          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
          Judge rerank (OpenJev relevance scoring)
        </label>
        {docSets.length > 0 && (
          <select
            value={docSetId}
            onChange={(e) => setDocSetId(e.target.value)}
            className="text-xs border border-gray-300 rounded px-2 py-1"
            title="Scope search to a doc-set"
          >
            <option value="">All documents</option>
            {docSets.map(s => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.kind})
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="text-sm text-red-600 mb-3">{error}</div>}

      <div className="space-y-3">
        {hits.map((h, i) => (
          <div key={`${h.doc_id}-${i}`} className="border border-gray-200 rounded p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-sm text-gray-800">{h.doc_id}</span>
              <span className="text-xs px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded">{h.doc_type}</span>
              <span className="text-xs text-gray-400">vector {h.score}</span>
              {h.judge_score !== undefined && (
                <span className="text-xs px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded">
                  judge {(h.judge_score * 100).toFixed(0)}%
                </span>
              )}
              {h.source?.url && (
                <a
                  href={h.source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-xs text-blue-600 hover:underline"
                >
                  open ↗
                </a>
              )}
              {docSetId && docSets.find(x => x.id === docSetId)?.kind === "pinned" && (
                <button
                  onClick={() => pinHit(h.doc_id)}
                  className="text-xs text-purple-600 hover:underline"
                  title="Pin into selected set"
                >
                  📌 pin
                </button>
              )}
              <button
                onClick={() => openEvidence(h.doc_id)}
                className={`${h.source?.url ? "" : "ml-auto"} text-xs text-blue-600 hover:underline`}
              >
                Evidence →
              </button>
            </div>
            <p className="text-xs text-gray-600 whitespace-pre-wrap line-clamp-4">{h.chunk_to_retrieve}</p>
          </div>
        ))}
        {!loading && hits.length === 0 && question && !error && (
          <p className="text-sm text-gray-400">No results.</p>
        )}
      </div>

      {evidenceLoading && <p className="text-sm text-gray-400 mt-4">Loading evidence…</p>}
      {evidence && (
        <div className="mt-6 border-t border-gray-200 pt-4">
          <h3 className="text-base font-semibold text-gray-800 mb-2">
            Evidence — {evidence.document.doc_id}
            <span className="ml-2 text-xs px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded">
              {evidence.document.doc_type}
            </span>
          </h3>
          <p className="text-xs text-gray-400 mb-3 font-mono">{evidence.document.source_file}</p>

          <div className="flex items-center gap-2 mb-1">
            <h4 className="text-sm font-medium text-gray-700">Extracted fields</h4>
            {!evidence.validation && (
              <button
                onClick={() => openEvidence(evidence.document.doc_id, true)}
                disabled={validating}
                className="text-xs px-2 py-0.5 bg-emerald-600 text-white rounded disabled:opacity-50"
              >
                {validating ? "Judging…" : "Validate with judge"}
              </button>
            )}
            {evidence.validation?.type_check && (
              <span
                className={`text-xs px-1.5 py-0.5 rounded ${
                  evidence.validation.type_check.match
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-amber-100 text-amber-700"
                }`}
              >
                type: {evidence.validation.type_check.extracted_type}
                {evidence.validation.type_check.match
                  ? " ✓"
                  : ` → judge says ${evidence.validation.type_check.judge_choice}`}{" "}
                ({(evidence.validation.type_check.confidence * 100).toFixed(0)}%)
              </span>
            )}
            {evidence.validation?.error && (
              <span className="text-xs text-gray-400">judge unavailable</span>
            )}
          </div>
          <table className="w-full text-xs mb-4 border border-gray-200">
            <tbody>
              {evidence.extracted_fields.map((f) => {
                const conf = evidence.validation?.field_confidence?.[f.field_name];
                return (
                  <tr key={f.field_name} className="border-b border-gray-100">
                    <td className="px-2 py-1 font-mono text-gray-500 w-1/3">{f.field_name}</td>
                    <td className="px-2 py-1 text-gray-800">
                      {f.field_value}
                      {conf !== undefined && (
                        <span
                          className={`ml-2 px-1 py-0.5 rounded ${
                            conf >= 0.7
                              ? "bg-emerald-100 text-emerald-700"
                              : conf >= 0.4
                                ? "bg-amber-100 text-amber-700"
                                : "bg-red-100 text-red-700"
                          }`}
                        >
                          {(conf * 100).toFixed(0)}%
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <h4 className="text-sm font-medium text-gray-700 mb-1">Source chunks</h4>
          <div className="space-y-2">
            {evidence.source_chunks.map((c) => (
              <details key={c.chunk_position} className="border border-gray-200 rounded p-2">
                <summary className="text-xs text-gray-500 cursor-pointer">
                  Chunk {c.chunk_position} — {c.source_text.slice(0, 80)}…
                </summary>
                <p className="text-xs text-gray-600 whitespace-pre-wrap mt-1">{c.source_text}</p>
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
