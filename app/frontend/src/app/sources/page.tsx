"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";

interface Source {
  source_id:    string;
  provider:     string;
  display_name: string;
  auth_mode:    string;
  status:       string;
  mode:         string;
  last_crawl_at: string | null;
  last_error:   string;
  created_at:   string;
}

interface CrawlResult {
  source_id:  string;
  discovered: number;
  folders:    number;
  seen_ids:   string[];
}

const STATUS_STYLE: Record<string, { badge: string; label: string }> = {
  connected:    { badge: "bg-green-100 text-green-700",  label: "Connected"    },
  active:       { badge: "bg-green-100 text-green-700",  label: "Active"       },
  crawling:     { badge: "bg-blue-100 text-blue-700",    label: "Crawling"     },
  error:        { badge: "bg-red-100 text-red-700",      label: "Error"        },
  disconnected: { badge: "bg-gray-100 text-gray-500",    label: "Disconnected" },
};

export default function SourcesPage({ domain }: { domain: DomainInfo }) {
  const { project } = useDomain();

  const [sources,      setSources]      = useState<Source[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [msg,          setMsg]          = useState<string | null>(null);
  const [crawling,     setCrawling]     = useState<Record<string, boolean>>({});
  const [crawlResults, setCrawlResults] = useState<Record<string, CrawlResult>>({});
  const [showForm,     setShowForm]     = useState(false);
  const [managedFolder, setManagedFolder] = useState<Record<string, string>>({});

  // Register-new-source form state
  const [newId,          setNewId]          = useState("gdrive");
  const [newProvider,    setNewProvider]    = useState("gdrive_managed");
  const [newDisplayName, setNewDisplayName] = useState("Google Drive");
  const [registering,    setRegistering]    = useState(false);

  const fetchSources = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiCall<{ sources: Source[] }>("/api/sources");
      setSources(r.sources ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  async function connect(sourceId: string) {
    setMsg(null);
    try {
      const r = await apiCall<{ url: string }>(`/api/sources/${sourceId}/auth-url`);
      if (r.url) window.open(r.url, "_blank");
      else       setMsg("No OAuth URL returned — source may not support this auth mode.");
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setMsg(
        m.includes("synthetic mode")
          ? `${m} Use a "Google Drive (managed — no setup)" source instead — it works without Google OAuth credentials.`
          : m
      );
    }
  }

  async function crawl(sourceId: string) {
    if (!project?.project_id) {
      setMsg("Select a project first (use the project picker in the toolbar).");
      return;
    }
    setCrawling(c => ({ ...c, [sourceId]: true }));
    setMsg(null);
    try {
      const r = await apiCall<CrawlResult>(`/api/sources/${sourceId}/crawl`, {
        method: "POST",
        body: JSON.stringify({
          domain_id:   domain.domain_id,
          project_id:  project.project_id,
          root_folder: "",
        }),
      });
      setCrawlResults(prev => ({ ...prev, [sourceId]: r }));
      setMsg(
        `Crawl complete — discovered ${r.discovered} file(s) in ${r.folders} folder(s).`
      );
      fetchSources();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setCrawling(c => ({ ...c, [sourceId]: false }));
    }
  }

  async function managedCrawl(sourceId: string, folderId: string) {
    if (!project?.project_id) { setMsg("Select a project first."); return; }
    setCrawling(c => ({ ...c, [sourceId]: true })); setMsg(null);
    try {
      const r = await apiCall<{ job_id: string; summary: { embedded: number; skipped: number; failed: number }; skipped_binary: number }>(
        `/api/sources/${sourceId}/managed-crawl`,
        { method: "POST", body: JSON.stringify({ domain_id: domain.domain_id, project_id: project.project_id, root_folder: folderId }) },
      );
      setMsg(`Indexed ${r.summary.embedded} file(s); ${r.skipped_binary} non-text file(s) listed but not indexed.`);
      fetchSources();
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setMsg(m.includes("401") || m.includes("403") ? "Authorize the app for AI Gateway access, then retry." : m);
    } finally {
      setCrawling(c => ({ ...c, [sourceId]: false }));
    }
  }

  async function registerSource() {
    setRegistering(true);
    setMsg(null);
    try {
      await apiCall("/api/sources", {
        method: "POST",
        body: JSON.stringify({
          source_id:      newId.trim(),
          provider:       newProvider,
          display_name:   newDisplayName.trim(),
          auth_mode:      "oauth2",
          credential_ref: "",
          site:           "",
          mode:           "live",
        }),
      });
      setShowForm(false);
      setMsg(`Source "${newDisplayName}" registered.`);
      fetchSources();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setRegistering(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Connected Sources</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Register and connect external data sources. Metadata is crawled without
            copying document content.
          </p>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex-shrink-0 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
        >
          <span className="text-base leading-none">+</span> Add Source
        </button>
      </div>

      {/* Non-sensitive data notice */}
      <div className="mb-4 flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
        <span className="flex-shrink-0 mt-0.5">⚠️</span>
        <span>
          Connect only sources containing{" "}
          <strong>non-sensitive, non-confidential documents</strong>. Do not connect
          drives with personal data, PII, credentials, or regulated records.
        </span>
      </div>

      {/* Register form */}
      {showForm && (
        <div className="mb-4 bg-white border border-blue-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-800 mb-4">Register a new source</h3>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Source ID
              </label>
              <input
                value={newId}
                onChange={e => setNewId(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                placeholder="gdrive"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Provider
              </label>
              <select
                value={newProvider}
                onChange={e => setNewProvider(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                <option value="gdrive_managed">Google Drive (managed — workspace connector)</option>
                <option value="sharepoint">SharePoint / OneDrive</option>
                <option value="s3">AWS S3</option>
                <option value="gcs">Google Cloud Storage</option>
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Display Name
              </label>
              <input
                value={newDisplayName}
                onChange={e => setNewDisplayName(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
                placeholder="My Google Drive"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={registerSource}
              disabled={registering || !newId.trim() || !newDisplayName.trim()}
              className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-1.5 rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
            >
              {registering ? "Registering…" : "Register"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg cursor-pointer"
            >
              Cancel
            </button>
          </div>
          <p className="mt-3 text-[11px] text-gray-400">
            <strong>Google Drive (managed)</strong> needs no OAuth setup — register, then
            <strong> Connect &amp; Crawl</strong> with a Drive folder ID. Plain
            <strong> Google Drive</strong> requires a Google Cloud OAuth client first.
          </p>
        </div>
      )}

      {msg && (
        <div className="mb-4 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg p-3">
          {msg}
        </div>
      )}

      {loading ? (
        <div className="text-center text-gray-400 py-12 text-sm">Loading sources…</div>
      ) : sources.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl py-14 flex flex-col items-center text-center">
          <span className="text-4xl mb-3">🔌</span>
          <h3 className="text-base font-bold text-gray-800 mb-1.5">No sources registered</h3>
          <p className="text-sm text-gray-500 max-w-sm mb-5">
            Connect Google Drive, SharePoint, or S3 to start syncing document
            metadata without copying file content.
          </p>
          <button
            onClick={() => setShowForm(true)}
            className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-5 py-2.5 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            <span className="text-base leading-none">+</span> Add your first source
          </button>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Column headers */}
          <div className="grid grid-cols-12 bg-gray-50 border-b border-gray-200 px-4 py-2 text-[10px] font-bold text-gray-500 uppercase tracking-wide">
            <span className="col-span-4">Source</span>
            <span className="col-span-2">Provider</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-2">Last crawl</span>
            <span className="col-span-2">Actions</span>
          </div>

          {sources.map((src, i) => {
            const st  = STATUS_STYLE[src.status] ?? STATUS_STYLE.disconnected;
            const cr  = crawlResults[src.source_id];
            const isCrawling = !!crawling[src.source_id];
            return (
              <div
                key={src.source_id}
                className={`grid grid-cols-12 px-4 py-3 border-b border-gray-50 last:border-0 items-start text-sm ${
                  i % 2 === 0 ? "bg-white" : "bg-gray-50/40"
                }`}
              >
                {/* Name + source_id */}
                <div className="col-span-4 min-w-0">
                  <p className="font-semibold text-gray-800 truncate">{src.display_name}</p>
                  <p className="text-xs text-gray-400 font-mono truncate">{src.source_id}</p>
                  {cr && (
                    <p className="text-xs text-green-600 mt-0.5">
                      {cr.discovered} file{cr.discovered !== 1 ? "s" : ""} in {cr.folders} folder{cr.folders !== 1 ? "s" : ""}
                    </p>
                  )}
                  {src.last_error && (
                    <p className="text-xs text-red-500 mt-0.5 truncate" title={src.last_error}>
                      {src.last_error}
                    </p>
                  )}
                </div>

                {/* Provider */}
                <span className="col-span-2 text-xs text-gray-600 self-center">{src.provider}</span>

                {/* Status badge */}
                <span className="col-span-2 self-center">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${st.badge}`}>
                    {st.label}
                  </span>
                </span>

                {/* Last crawl */}
                <span className="col-span-2 text-xs text-gray-400 self-center">
                  {src.last_crawl_at
                    ? new Date(src.last_crawl_at).toLocaleDateString()
                    : "—"}
                </span>

                {/* Action buttons */}
                <div className="col-span-2 flex flex-wrap gap-1.5 self-center">
                  {src.status === "disconnected" && src.provider !== "gdrive_managed" && (
                    <button
                      onClick={() => connect(src.source_id)}
                      className="text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      Connect
                    </button>
                  )}
                  {src.provider !== "gdrive_managed" && (
                    <button
                      onClick={() => crawl(src.source_id)}
                      disabled={isCrawling}
                      className="text-xs font-semibold text-gray-600 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                      title={!project ? "Select a project first" : "Sync file metadata for the selected project"}
                    >
                      {isCrawling ? "Crawling…" : "Crawl"}
                    </button>
                  )}
                  {src.provider === "gdrive_managed" && (
                    <div className="flex flex-col gap-1 w-full">
                      <input
                        value={managedFolder[src.source_id] ?? ""}
                        onChange={e => setManagedFolder(f => ({ ...f, [src.source_id]: e.target.value }))}
                        placeholder="Folder ID (optional)"
                        className="text-xs border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-400 w-full"
                      />
                      <button
                        onClick={() => managedCrawl(src.source_id, managedFolder[src.source_id] ?? "")}
                        disabled={isCrawling}
                        className="text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                        title={!project ? "Select a project first" : "Index files from the managed Drive"}
                      >
                        {isCrawling ? "Indexing…" : "Connect & Crawl"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!project && sources.length > 0 && (
        <p className="mt-3 text-xs text-gray-400">
          Select a project in the toolbar to enable the Crawl action for that project.
        </p>
      )}
    </div>
  );
}
