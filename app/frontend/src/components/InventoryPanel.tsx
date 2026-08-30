"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiCall } from "@/lib/api-config";

interface ExternalDoc {
  external_document_id: string;
  source_id: string;
  name: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  web_url: string;
  status: string;
  included: boolean;
  chunk_count: number;
  source_modified_at: string | null;
  last_error: string;
}

interface IndexJob {
  job_id:        string;
  status:        string; // queued | running | done | failed
  discovered:    number;
  embedded:      number;
  skipped:       number;
  failed:        number;
  started_at:    string | null;
  finished_at:   string | null;
  error_summary: string;
}

const STATUS_CHIP: Record<string, string> = {
  indexed:          "bg-green-100 text-green-700",
  stale:            "bg-yellow-100 text-yellow-700",
  discovered:       "bg-gray-100 text-gray-500",
  "metadata-only":  "bg-gray-100 text-gray-500",
  failed:           "bg-red-100 text-red-700",
  deleted:          "bg-red-50 text-red-400",
};

function jobStatusColor(status: string) {
  if (status === "done")    return "text-green-600";
  if (status === "failed")  return "text-red-600";
  if (status === "running") return "text-blue-600";
  return "text-gray-500";
}

function formatSize(bytes: number) {
  if (!bytes) return "—";
  if (bytes < 1024)             return `${bytes} B`;
  if (bytes < 1024 * 1024)      return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function InventoryPanel({
  domainId,
  projectId,
}: {
  domainId: string;
  projectId: string;
}) {
  const [docs,         setDocs]         = useState<ExternalDoc[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [msg,          setMsg]          = useState<string | null>(null);
  const [activeJob,    setActiveJob]    = useState<IndexJob | null>(null);
  const [submitting,   setSubmitting]   = useState(false);
  const [included,     setIncluded]     = useState<Record<string, boolean>>({});
  const [selSource,    setSelSource]    = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchInventory = useCallback(async () => {
    if (!domainId || !projectId) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await apiCall<{ documents: ExternalDoc[] }>(
        `/api/inventory?domain_id=${encodeURIComponent(domainId)}&project_id=${encodeURIComponent(projectId)}`
      );
      const rows = r.documents ?? [];
      setDocs(rows);
      const incMap: Record<string, boolean> = {};
      rows.forEach(d => { incMap[d.external_document_id] = d.included; });
      setIncluded(incMap);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [domainId, projectId]);

  useEffect(() => { fetchInventory(); }, [fetchInventory]);

  // Cleanup poll on unmount
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  function startPolling(jobId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiCall<{ job: IndexJob }>(`/api/index-jobs/${jobId}`);
        const job = r.job;
        setActiveJob(job);
        if (job.status === "done" || job.status === "failed") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          fetchInventory();
        }
      } catch { /* ignore transient poll errors */ }
    }, 2000);
  }

  const sourceIds = Array.from(new Set(docs.map(d => d.source_id).filter(Boolean)));

  async function buildIndex() {
    const sourceId = selSource || sourceIds[0] || "";
    if (!sourceId) {
      setMsg("No documents in inventory. Connect a source and run a crawl first.");
      return;
    }
    setSubmitting(true);
    setMsg(null);
    try {
      const r = await apiCall<{ job_id: string }>("/api/index-jobs", {
        method: "POST",
        body: JSON.stringify({
          source_id:    sourceId,
          domain_id:    domainId,
          project_id:   projectId,
          scope:        "project",
          scope_ref:    projectId,
          requested_by: "app_user",
        }),
      });
      const stub: IndexJob = {
        job_id: r.job_id, status: "queued",
        discovered: 0, embedded: 0, skipped: 0, failed: 0,
        started_at: null, finished_at: null, error_summary: "",
      };
      setActiveJob(stub);
      startPolling(r.job_id);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const progress   = activeJob?.discovered
    ? Math.min(100, (activeJob.embedded / activeJob.discovered) * 100)
    : 0;

  return (
    <div>
      {/* Index job bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {sourceIds.length > 1 && (
          <select
            value={selSource}
            onChange={e => setSelSource(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="">— select source —</option>
            {sourceIds.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {sourceIds.length === 1 && (
          <span className="text-xs text-gray-500">
            Source: <strong className="text-gray-700">{sourceIds[0]}</strong>
          </span>
        )}
        <button
          onClick={buildIndex}
          disabled={submitting || jobRunning || (sourceIds.length > 1 && !selSource)}
          className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-1.5 rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
        >
          {submitting || jobRunning ? "Indexing…" : "Build / Refresh index"}
        </button>
        {sourceIds.length === 0 && !loading && (
          <span className="text-xs text-gray-400">
            No documents. Connect a source in the Sources tab and run a Crawl.
          </span>
        )}
      </div>

      {/* Job progress bar */}
      {activeJob && (
        <div className="mb-4 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold text-blue-800">
              Index job{" "}
              <span className="font-mono text-xs">{activeJob.job_id.slice(0, 8)}…</span>
            </span>
            <span className={`text-xs font-bold uppercase ${jobStatusColor(activeJob.status)}`}>
              {activeJob.status}
            </span>
          </div>
          {activeJob.status === "running" && (
            <div className="w-full h-1.5 bg-blue-200 rounded-full overflow-hidden mb-2">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
          <div className="flex gap-4 text-xs text-blue-700">
            <span>Discovered <strong>{activeJob.discovered}</strong></span>
            <span>Embedded <strong>{activeJob.embedded}</strong></span>
            {activeJob.skipped > 0 && <span>Skipped {activeJob.skipped}</span>}
            {activeJob.failed  > 0 && <span className="text-red-600">Failed {activeJob.failed}</span>}
          </div>
          {activeJob.error_summary && (
            <p className="mt-1 text-xs text-red-600">{activeJob.error_summary}</p>
          )}
        </div>
      )}

      {msg && (
        <div className="mb-3 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2">
          {msg}
        </div>
      )}

      {loading ? (
        <div className="text-center text-gray-400 py-10 text-sm">Loading inventory…</div>
      ) : docs.length === 0 ? (
        <div className="text-center text-gray-400 py-10 text-sm">
          No documents for this project yet. Connect a source and run a Crawl.
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Column headers */}
          <div className="grid grid-cols-12 bg-gray-50 border-b border-gray-200 px-3 py-2 text-[10px] font-bold text-gray-500 uppercase tracking-wide">
            <span className="col-span-1 text-center">Inc.</span>
            <span className="col-span-4">Name</span>
            <span className="col-span-2 hidden md:block">Path</span>
            <span className="col-span-1">Type</span>
            <span className="col-span-1 hidden sm:block">Size</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-1 text-center">Chunks</span>
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {docs.map((doc, i) => {
              const chipClass = STATUS_CHIP[doc.status] ?? STATUS_CHIP.discovered;
              const isIncluded = included[doc.external_document_id] ?? doc.included;
              const mimeShort = doc.mime_type ? doc.mime_type.split("/").pop() ?? "—" : "—";
              return (
                <div
                  key={doc.external_document_id}
                  className={`grid grid-cols-12 px-3 py-2 border-b border-gray-50 last:border-0 items-center text-xs ${
                    i % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                  }`}
                >
                  <span className="col-span-1 flex justify-center">
                    <input
                      type="checkbox"
                      checked={isIncluded}
                      onChange={e =>
                        setIncluded(prev => ({
                          ...prev,
                          [doc.external_document_id]: e.target.checked,
                        }))
                      }
                      className="cursor-pointer"
                      title="Include in index"
                    />
                  </span>
                  <span className="col-span-4 font-medium text-gray-800 truncate" title={doc.name}>
                    {doc.web_url ? (
                      <a
                        href={doc.web_url}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-blue-600 hover:underline"
                      >
                        {doc.name || "(untitled)"}
                      </a>
                    ) : (
                      doc.name || "(untitled)"
                    )}
                  </span>
                  <span
                    className="col-span-2 text-gray-400 truncate font-mono text-[10px] hidden md:block"
                    title={doc.path}
                  >
                    {doc.path ? doc.path.split("/").slice(-2).join("/") : "—"}
                  </span>
                  <span className="col-span-1 text-gray-400 truncate text-[10px]">
                    {mimeShort.toUpperCase().slice(0, 5)}
                  </span>
                  <span className="col-span-1 text-gray-400 hidden sm:block">
                    {formatSize(doc.size_bytes)}
                  </span>
                  <span className="col-span-2">
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${chipClass}`}
                    >
                      {doc.status}
                    </span>
                    {doc.last_error && (
                      <span
                        className="ml-1 text-[10px] text-red-400 cursor-help"
                        title={doc.last_error}
                      >
                        !
                      </span>
                    )}
                  </span>
                  <span className="col-span-1 text-gray-400 text-center">
                    {doc.chunk_count > 0 ? doc.chunk_count : "—"}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="px-3 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between text-[10px] text-gray-400">
            <span>
              {docs.length} document{docs.length !== 1 ? "s" : ""}
            </span>
            <span className="italic">Inclusion changes are local-only until persisted.</span>
          </div>
        </div>
      )}
    </div>
  );
}
