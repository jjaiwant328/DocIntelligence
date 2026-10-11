"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { DomainContext, DEMO_USERS } from "@/context/DomainContext";
import type { DomainInfo, ProjectInfo } from "@/context/DomainContext";
import SpineSearchPanel from "@/components/SpineSearchPanel";

const SourcesTab = dynamic(() => import("./sources/page"), {
  ssr: false,
  loading: () => <LoadingPane label="Sources" />,
});
const AgentTab = dynamic(() => import("./agent/page"), {
  ssr: false,
  loading: () => <LoadingPane label="Agent" />,
});

function LoadingPane({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-64 text-gray-400">
      <div className="text-center">
        <div className="text-3xl mb-3 animate-spin inline-block">⟳</div>
        <p className="text-sm">Loading {label}…</p>
      </div>
    </div>
  );
}

const TABS = [
  { id: "sources", icon: "🔌", label: "Sources", description: "Connect a source, crawl metadata, build the index." },
  { id: "search",  icon: "🔍", label: "Search & Evidence", description: "Judge-reranked semantic search with an evidence trail per hit." },
  { id: "agent",   icon: "🧠", label: "Agent", description: "Ask questions across the corpus; grounded answers with cited sources." },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function Home() {
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [domainsLoading, setDomainsLoading] = useState(true);
  const [activeDomain, setActiveDomain] = useState<DomainInfo | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("sources");
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [actingUser, setActingUser] = useState<string>(DEMO_USERS[0]);
  const [enforceAccess, setEnforceAccess] = useState<boolean>(false);

  const fetchDomains = useCallback(async () => {
    setDomainsLoading(true);
    try {
      const res = await fetch("/api/spine/domains");
      if (res.ok) {
        const data = await res.json();
        setDomains(
          (data.domains ?? []).map((d: { domain_id: string }) => ({
            domain_id: d.domain_id,
            name: d.domain_id.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()),
            status: "active",
          }))
        );
      }
    } catch {
      setDomains([]);
    } finally {
      setDomainsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDomains();
  }, [fetchDomains]);

  // Restore domain + tab from URL after domains load
  useEffect(() => {
    if (domainsLoading || domains.length === 0 || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const urlDomain = params.get("domain");
    const urlTab = (params.get("tab") ?? "sources") as TabId;
    if (urlDomain) {
      const match = domains.find((d) => d.domain_id === urlDomain) ?? {
        domain_id: urlDomain,
        name: urlDomain.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        status: "active",
      };
      setActiveDomain(match);
      setActiveTab(TABS.some((t) => t.id === urlTab) ? urlTab : "sources");
    }
  }, [domainsLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  const syncUrl = (domainId: string | null, tab: TabId) => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    if (domainId) {
      params.set("domain", domainId);
      params.set("tab", tab);
    }
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  };

  const openDomain = (d: DomainInfo) => {
    setActiveDomain(d);
    setProject(null);
    setActiveTab("sources");
    syncUrl(d.domain_id, "sources");
  };

  const switchTab = (tab: TabId) => {
    setActiveTab(tab);
    if (activeDomain) syncUrl(activeDomain.domain_id, tab);
  };

  // ── Landing: domain cards ──────────────────────────────────────────────────
  if (!activeDomain) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto px-6 py-12">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">DocIntelligence</h1>
          <p className="text-sm text-gray-500 mb-8">
            Connect sources, search the corpus, inspect the evidence. Pick a domain to open its workspace.
          </p>
          {domainsLoading ? (
            <LoadingPane label="domains" />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {domains.map((d) => (
                <button
                  key={d.domain_id}
                  onClick={() => openDomain(d)}
                  className="text-left bg-white border border-gray-200 rounded-lg p-5 hover:border-blue-400 hover:shadow-sm transition"
                >
                  <div className="text-base font-semibold text-gray-800">{d.name}</div>
                  <div className="text-xs font-mono text-gray-400 mt-1">{d.domain_id}</div>
                  <div className="text-xs text-blue-600 mt-3">Open workspace →</div>
                </button>
              ))}
              {domains.length === 0 && (
                <p className="text-sm text-gray-400">No spine domains configured.</p>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Workspace: 3 tabs over the spine ───────────────────────────────────────
  const ctx = {
    domain: activeDomain,
    setDomain: (d: DomainInfo) => setActiveDomain(d),
    project,
    setProject,
    actingUser,
    setActingUser,
    enforceAccess,
    setEnforceAccess,
  };

  return (
    <DomainContext.Provider value={ctx}>
      <div className="min-h-screen bg-gray-50">
        <div className="bg-white border-b border-gray-200">
          <div className="max-w-7xl mx-auto px-4 pt-3 pb-0">
            <div className="flex items-center gap-2 text-sm mb-2">
              <button onClick={() => { setActiveDomain(null); syncUrl(null, "sources"); }} className="text-blue-600 hover:underline">
                Domains
              </button>
              <span className="text-gray-300">›</span>
              <span className="font-semibold text-gray-800">{activeDomain.name}</span>
            </div>
            <div className="flex gap-1">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => switchTab(t.id)}
                  title={t.description}
                  className={`px-3 py-2 text-sm rounded-t border-b-2 ${
                    activeTab === t.id
                      ? "border-blue-600 text-blue-700 font-medium bg-blue-50"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {activeTab === "sources" && <SourcesTab domain={activeDomain} />}
        {activeTab === "search" && <SpineSearchPanel domain={activeDomain} />}
        {activeTab === "agent" && <AgentTab domain={activeDomain} />}
      </div>
    </DomainContext.Provider>
  );
}
