"use client";

import { useState } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

interface CopilotSections {
  facts?: string; interpretations?: string; sources?: string;
  risks?: string; open_questions?: string; next_steps?: string;
}
interface CopilotResult {
  sections: CopilotSections; attorney_review: boolean; cited_docs: string[];
  raw_answer: string; query: string; confidence?: string; source_tier?: string;
}

const SECTION_ORDER: { key: keyof CopilotSections; label: string }[] = [
  { key: "facts", label: "Facts" },
  { key: "interpretations", label: "Interpretations" },
  { key: "risks", label: "Risks" },
  { key: "open_questions", label: "Open Questions" },
  { key: "next_steps", label: "Recommended Next Steps" },
  { key: "sources", label: "Sources" },
];

function confidenceColor(c?: string): string {
  if (c === "HIGH") return "bg-green-100 text-green-800";
  if (c === "MEDIUM") return "bg-amber-100 text-amber-800";
  if (c === "LOW") return "bg-orange-100 text-orange-800";
  return "bg-gray-200 text-gray-700";
}

export default function CopilotPage({ domain }: { domain?: DomainInfo }) {
  const domainId = domain?.domain_id ?? "compliance_due_diligence";
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<CopilotResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    if (!query.trim()) return;
    setLoading(true); setError(null);
    try {
      const r = await apiCall<CopilotResult>("/api/docintel/copilot-query", {
        method: "POST",
        body: JSON.stringify({ query, domain_id: domainId }),
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  return (
    <div className="px-4 py-4 max-w-4xl mx-auto">
      <p className="text-sm text-gray-500 mb-3">
        Ask questions across <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>&apos;s
        documents. Answers are grounded in your corpus with cited sources.
      </p>

      <div className="flex gap-2">
        <input
          className="flex-1 border rounded px-3 py-2 text-sm"
          placeholder="e.g. What licenses does Store 1827 still need?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
        />
        <button onClick={ask} disabled={loading}
          className="bg-blue-600 text-white text-sm rounded px-4 py-2 disabled:opacity-50">
          {loading ? "Asking…" : "Ask"}
        </button>
      </div>

      {error && <div className="mt-3 border border-red-200 bg-red-50 text-red-700 text-sm rounded p-3">{error}</div>}

      {result && (
        <div className="mt-5">
          <div className="flex items-center gap-2 mb-3">
            {result.confidence && (
              <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(result.confidence)}`}>
                confidence: {result.confidence}
              </span>
            )}
            {result.attorney_review && (
              <span className="text-xs px-2 py-0.5 rounded bg-purple-100 text-purple-800">flagged for review</span>
            )}
            {result.source_tier && (
              <span className="text-xs text-gray-400">source: {result.source_tier}</span>
            )}
          </div>

          {SECTION_ORDER.filter((s) => result.sections?.[s.key]).map((s) => (
            <div key={s.key} className="mb-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{s.label}</p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">{result.sections[s.key]}</p>
            </div>
          ))}

          {!Object.keys(result.sections || {}).length && (
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{result.raw_answer}</p>
          )}

          {result.cited_docs?.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-semibold text-gray-500">Cited documents</p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {result.cited_docs.map((d) => (
                  <li key={d} className="text-xs font-mono bg-gray-100 rounded px-1.5 py-0.5">{d}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
