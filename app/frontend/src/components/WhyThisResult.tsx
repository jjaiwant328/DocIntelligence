"use client";

export interface SearchResult {
  chunk_id: string;
  external_document_id: string;
  name: string;
  path: string;
  web_url: string;
  mime_type: string;
  status: string;
  ordinal: number;
  location: string;
  snippet: string;
  score: number;
}

export function WhyThisResult({
  result,
  onClose,
}: {
  result: SearchResult;
  onClose: () => void;
}) {
  return (
    <div className="bg-white border border-blue-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-gray-800">Why this result?</h4>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-xs cursor-pointer"
        >
          ✕ close
        </button>
      </div>

      {/* Retrieval mode */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-700">
          Hybrid · Vector + Full-Text
        </span>
        <span className="text-[10px] text-gray-400">
          RRF score {result.score.toFixed(5)}
        </span>
      </div>

      {/* Matched chunk */}
      <div className="bg-gray-50 rounded-lg p-3 mb-3">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
          Matched chunk — ordinal {result.ordinal + 1}
          {result.location ? ` · ${result.location}` : ""}
        </p>
        <p className="text-xs text-gray-700 leading-relaxed line-clamp-8">
          {result.snippet || "(no snippet available)"}
        </p>
      </div>

      {/* Source metadata */}
      <div className="space-y-1 text-xs">
        <div className="flex gap-2">
          <span className="text-gray-400 w-20 flex-shrink-0">Document</span>
          <span className="text-gray-700 truncate font-medium">{result.name || "(untitled)"}</span>
        </div>
        {result.path && (
          <div className="flex gap-2">
            <span className="text-gray-400 w-20 flex-shrink-0">Path</span>
            <span className="text-gray-500 truncate font-mono text-[10px]">{result.path}</span>
          </div>
        )}
        {result.mime_type && (
          <div className="flex gap-2">
            <span className="text-gray-400 w-20 flex-shrink-0">MIME type</span>
            <span className="text-gray-500">{result.mime_type}</span>
          </div>
        )}
        <div className="flex gap-2">
          <span className="text-gray-400 w-20 flex-shrink-0">Chunk ID</span>
          <span className="font-mono text-[10px] text-gray-400 truncate">{result.chunk_id}</span>
        </div>
        {result.status && (
          <div className="flex gap-2">
            <span className="text-gray-400 w-20 flex-shrink-0">Index status</span>
            <span className="text-gray-600">{result.status}</span>
          </div>
        )}
      </div>
    </div>
  );
}
