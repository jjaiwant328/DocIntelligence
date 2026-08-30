"use client";

import { useState } from "react";
import { apiCall } from "@/lib/api-config";
import { WhyThisResult } from "./WhyThisResult";
import type { SearchResult } from "./WhyThisResult";

const STATUS_CHIP: Record<string, string> = {
  indexed: "bg-green-100 text-green-700",
  stale:   "bg-yellow-100 text-yellow-700",
  failed:  "bg-red-100 text-red-700",
};

function mimeLabel(mime: string): string {
  if (!mime) return "";
  const part = mime.split("/").pop() ?? mime;
  const MAP: Record<string, string> = {
    "pdf":                              "PDF",
    "vnd.google-apps.document":         "GDoc",
    "vnd.google-apps.spreadsheet":      "GSheet",
    "vnd.google-apps.presentation":     "GSlides",
    "vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "vnd.openxmlformats-officedocument.spreadsheetml.sheet":       "XLSX",
    "vnd.ms-excel":    "XLS",
    "msword":          "DOC",
    "plain":           "TXT",
    "html":            "HTML",
  };
  return MAP[part] ?? part.toUpperCase().slice(0, 6);
}

export function SearchPanel({
  domainId,
  projectId,
}: {
  domainId: string;
  projectId: string;
}) {
  const [query, setQuery]       = useState("");
  const [results, setResults]   = useState<SearchResult[]>([]);
  const [loading, setLoading]   = useState(false);
  const [searched, setSearched] = useState(false);
  const [msg, setMsg]           = useState<string | null>(null);
  const [whyId, setWhyId]       = useState<string | null>(null);

  async function search() {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setMsg(null);
    setSearched(false);
    setResults([]);
    try {
      const r = await apiCall<{ results: SearchResult[]; total: number }>("/api/search", {
        method: "POST",
        body: JSON.stringify({
          domain_id:  domainId,
          project_id: projectId,
          query:      q,
          k:          10,
        }),
      });
      const rows = r.results ?? [];
      setResults(rows);
      setSearched(true);
      if (rows.length === 0) {
        setMsg(`No results for "${q}" — make sure documents are indexed in the Inventory tab.`);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      {/* Search input */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && search()}
          placeholder="Search this project's documents…"
          className="flex-1 text-sm border border-gray-200 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
          autoFocus
        />
        <button
          onClick={search}
          disabled={loading || !query.trim()}
          className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-5 py-2 rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
        >
          {loading ? "…" : "Search"}
        </button>
      </div>

      {msg && (
        <div className="mb-3 text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2">
          {msg}
        </div>
      )}

      {!searched && !loading && !msg && (
        <div className="text-center text-gray-400 py-10 text-sm">
          <p className="mb-1">Hybrid vector + full-text search</p>
          <p className="text-xs">Enter a query to search indexed documents.</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-400 mb-3">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
          {results.map(r => (
            <div
              key={r.chunk_id}
              className="bg-white border border-gray-200 rounded-xl p-4 hover:border-blue-300 transition-colors"
            >
              {/* Header row */}
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-0.5">
                    <span className="text-sm font-semibold text-gray-800 truncate">
                      {r.web_url ? (
                        <a
                          href={r.web_url}
                          target="_blank"
                          rel="noreferrer"
                          className="hover:text-blue-600 hover:underline inline-flex items-center gap-1"
                        >
                          {r.name || "(untitled)"}
                          <span className="text-gray-300 text-xs">↗</span>
                        </a>
                      ) : (r.name || "(untitled)")}
                    </span>
                    {r.mime_type && (
                      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 flex-shrink-0">
                        {mimeLabel(r.mime_type)}
                      </span>
                    )}
                    {r.status && STATUS_CHIP[r.status] && (
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0 ${STATUS_CHIP[r.status]}`}>
                        {r.status}
                      </span>
                    )}
                  </div>
                  {r.path && (
                    <p className="text-[10px] text-gray-400 font-mono truncate">{r.path}</p>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className="text-[10px] text-gray-400 font-mono">
                    {r.score.toFixed(3)}
                  </span>
                  <button
                    onClick={() => setWhyId(whyId === r.chunk_id ? null : r.chunk_id)}
                    className="text-[10px] font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-2 py-0.5 rounded transition-colors cursor-pointer"
                  >
                    Why?
                  </button>
                </div>
              </div>

              {/* Snippet */}
              {r.snippet && (
                <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">
                  {r.snippet}
                </p>
              )}

              {/* WhyThisResult inline panel */}
              {whyId === r.chunk_id && (
                <div className="mt-3">
                  <WhyThisResult result={r} onClose={() => setWhyId(null)} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
