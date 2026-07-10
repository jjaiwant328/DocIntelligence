"use client";

import dynamic from "next/dynamic";
import { useState, useEffect, useCallback, useRef } from "react";
import { DomainContext, DomainInfo } from "@/context/DomainContext";
import Link from "next/link";
import { DocViewerPanel } from "@/components/DocViewerPanel";
import { PipelineRunProvider } from "@/context/PipelineRunContext";
import { PipelineStatusPopup } from "@/components/PipelineStatusPopup";

// Lazy-load each domain workspace module — now each receives domain as an explicit prop
const DocIntelligence = dynamic(() => import("./document-intelligence/page"), {
  ssr: false,
  loading: () => <LoadingPane label="Document Intelligence" />,
});
const ControlTower = dynamic(() => import("./supply-chain/page"), {
  ssr: false,
  loading: () => <LoadingPane label="Control Tower" />,
});
const AIAgent = dynamic(() => import("./agent/page"), {
  ssr: false,
  loading: () => <LoadingPane label="AI Agent" />,
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

const WORKSPACE_TABS = [
  {
    id: "doc",
    icon: "📄",
    label: "Document Intelligence",
    shortLabel: "Docs",
    badge: "Schema · Process",
    badgeColor: "bg-blue-100 text-blue-700",
    description: "Define schema, upload PDFs, parse with AI, extract structured fields and run the batch pipeline.",
  },
  {
    id: "library",
    icon: "📚",
    label: "Document Library",
    shortLabel: "Library",
    badge: "Parsed Docs",
    badgeColor: "bg-indigo-100 text-indigo-700",
    description: "Browse all parsed and extracted documents, run pipelines, and manage the document corpus.",
  },
  {
    id: "tower",
    icon: "📊",
    label: "Control Tower",
    shortLabel: "Control Tower",
    badge: "Live Analytics",
    badgeColor: "bg-green-100 text-green-700",
    description: "Incident overview, ontology map, supplier risk rankings, and action center.",
  },
  {
    id: "agent",
    icon: "🤖",
    label: "AI Agent",
    shortLabel: "AI Agent",
    badge: "FMAPIs · UC Tools",
    badgeColor: "bg-purple-100 text-purple-700",
    description: "Ask natural-language questions across documents, Delta tables, and the knowledge graph.",
  },
];

const STATUS_COLOR: Record<string, string> = {
  active:      "bg-green-100 text-green-700",
  configuring: "bg-yellow-100 text-yellow-700",
  paused:      "bg-gray-100 text-gray-500",
};

const DOMAIN_ICONS: Record<string, string> = {
  supply_chain: "🏭",
  compliance:   "⚖️",
  procurement:  "🛒",
  finance:      "💰",
  hr:           "👥",
  legal:        "📜",
};

export default function Home() {
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [domainsLoading, setDomainsLoading] = useState(true);

  // Landing page tab: "overview" | "areas"
  const [landingTab, setLandingTab] = useState<"overview" | "areas">("overview");

  // Live FMAPI model config
  const [modelConfig, setModelConfig] = useState<{
    agent_model: string; embed_model: string; setup_model: string;
    fallback_chain: string[]; available_models: string[]; resolved_live: boolean;
  } | null>(null);

  // Currently selected domain workspace
  const [activeDomain, setActiveDomain] = useState<DomainInfo | null>(null);
  const [activeTab, setActiveTab] = useState<string>("doc");

  const [domainCtxState, setDomainCtxState] = useState<DomainInfo>({
    domain_id: "supply_chain",
    name: "Supply Chain",
    status: "active",
    schema_ready: false,
  });

  // ── Global document search ─────────────────────────────────────────────────
  const [searchOpen,    setSearchOpen]    = useState(false);
  const [searchQuery,   setSearchQuery]   = useState("");
  const [searchMode,    setSearchMode]    = useState<"keyword"|"semantic">("keyword");
  const [searchResults, setSearchResults] = useState<{doc_id:string;filename:string;doc_type:string;snippet:string}[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [viewDocId,     setViewDocId]     = useState<string|null>(null);
  const searchDebounce  = useRef<ReturnType<typeof setTimeout>|null>(null);
  const searchInputRef  = useRef<HTMLInputElement|null>(null);

  // Open search with ⌘K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k" && activeDomain) {
        e.preventDefault();
        setSearchOpen(v => { if (!v) setTimeout(() => searchInputRef.current?.focus(), 50); return !v; });
      }
      if (e.key === "Escape") { setSearchOpen(false); setViewDocId(null); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeDomain]);

  // Debounced search
  useEffect(() => {
    if (!searchOpen || !searchQuery.trim()) { setSearchResults([]); return; }
    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(async () => {
      setSearchLoading(true);
      try {
        const r = await fetch(
          `/api/docintel/search-docs?domain_id=${encodeURIComponent(activeDomain?.domain_id ?? "supply_chain")}&q=${encodeURIComponent(searchQuery)}&mode=${searchMode}&limit=20`
        );
        if (r.ok) {
          const d = await r.json();
          setSearchResults(d.results ?? []);
        }
      } catch { /* silent */ }
      setSearchLoading(false);
    }, 350);
  }, [searchQuery, searchMode, searchOpen, activeDomain]);

  // ── URL persistence ────────────────────────────────────────────────────────
  // pushUrl  — creates a new history entry (back button works: domain open / close)
  // replaceUrl — overwrites current entry (tab switches within a domain)
  const pushUrl = useCallback((domainId: string | null, tab: string) => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    if (domainId) { params.set("domain", domainId); params.set("tab", tab); }
    const qs = params.toString();
    window.history.pushState({ domainId, tab }, "", qs ? `?${qs}` : window.location.pathname);
  }, []);

  const syncUrl = useCallback((domainId: string | null, tab: string) => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (domainId) {
      params.set("domain", domainId);
      params.set("tab", tab);
    } else {
      params.delete("domain");
      params.delete("tab");
    }
    const qs = params.toString();
    window.history.replaceState({ domainId, tab }, "", qs ? `?${qs}` : window.location.pathname);
  }, []);

  const fetchDomains = useCallback(async () => {
    setDomainsLoading(true);
    try {
      const res = await fetch("/api/platform/domains");
      if (res.ok) {
        const data = await res.json();
        if (data.domains && data.domains.length > 0) {
          setDomains(data.domains);
        } else {
          setDomains([{
            domain_id: "supply_chain",
            name: "Supply Chain",
            description: "QSR supply chain document intelligence — recalls, temperature excursions, supplier risk.",
            status: "active",
            doc_count: 0,
          }]);
        }
      }
    } catch {
      setDomains([{
        domain_id: "supply_chain",
        name: "Supply Chain",
        description: "QSR supply chain document intelligence",
        status: "active",
      }]);
    } finally {
      setDomainsLoading(false);
    }
  }, []);

  // ── Restore domain + tab from URL on first load ───────────────────────────
  useEffect(() => {
    fetchDomains();
  }, [fetchDomains]);

  // ── Fetch live FMAPI model config ────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/docintel/model-config")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setModelConfig(d); })
      .catch(() => {});
  }, []);

  // After domains load, check URL params and restore state
  useEffect(() => {
    if (domainsLoading || domains.length === 0) return;
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const urlDomain = params.get("domain");
    const urlTab    = params.get("tab") ?? "doc";
    if (urlDomain) {
      const match = domains.find(d => d.domain_id === urlDomain)
        ?? { domain_id: urlDomain, name: urlDomain.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), status: "active" };
      setActiveDomain(match);
      setDomainCtxState(match);
      setActiveTab(urlTab);
    }
  }, [domainsLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDomain = (d: DomainInfo) => {
    setActiveDomain(d);
    setDomainCtxState(d);
    setActiveTab("doc");
    pushUrl(d.domain_id, "doc");  // push so browser Back returns to landing
  };

  const closeDomain = () => {
    setActiveDomain(null);
    pushUrl(null, "doc");  // push so browser Forward returns to domain
  };

  const switchTab = (tab: string) => {
    setActiveTab(tab);
    if (activeDomain) syncUrl(activeDomain.domain_id, tab);
  };

  // ── Browser back/forward support ────────────────────────────────────────────
  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      const s = e.state as { domainId?: string; tab?: string } | null;
      if (s?.domainId) {
        const match = domains.find(d => d.domain_id === s.domainId)
          ?? { domain_id: s.domainId, name: s.domainId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), status: "active" };
        setActiveDomain(match);
        setDomainCtxState(match);
        setActiveTab(s.tab ?? "doc");
      } else {
        setActiveDomain(null);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [domains]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Landing: two-tab layout ────────────────────────────────────────────────
  if (!activeDomain) {
    return (
      <main className="flex-1 flex flex-col bg-gray-50">
        {/* Landing tab bar */}
        <div className="bg-white border-b border-gray-200 px-6 flex items-center gap-0 min-h-[48px] flex-shrink-0">
          <span className="text-xs font-bold text-gray-700 mr-5 hidden sm:block">DocIntelligence</span>
          {([
            { id: "overview", icon: "🗺", label: "Platform Overview",  desc: "Architecture, how-to guide, and available connectors." },
            { id: "areas",    icon: "📂", label: "Subject Areas",      desc: "Select or create a subject area to open its workspace." },
          ] as const).map(t => (
            <button
              key={t.id}
              onClick={() => setLandingTab(t.id)}
              title={t.desc}
              className={`group relative flex items-center gap-1.5 px-4 py-3 text-xs font-semibold border-b-2 transition-colors whitespace-nowrap
                ${landingTab === t.id
                  ? "border-blue-600 text-blue-700 bg-blue-50/40"
                  : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
                }`}
            >
              <span>{t.icon}</span>
              <span>{t.label}</span>
              {/* Tooltip */}
              <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-52 bg-gray-900 text-white text-[10px] rounded-lg px-3 py-2 leading-snug opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg text-left">
                <strong className="block mb-0.5">{t.label}</strong>
                {t.desc}
              </span>
            </button>
          ))}
          {/* Subject Areas count pill — always visible */}
          <div className="ml-auto flex items-center gap-2">
            {landingTab === "overview" && (
              <button
                onClick={() => setLandingTab("areas")}
                className="text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-full transition-colors flex items-center gap-1.5"
              >
                📂 {domainsLoading ? "…" : `${domains.length} Subject Area${domains.length !== 1 ? "s" : ""}`} →
              </button>
            )}
            {landingTab === "areas" && !domainsLoading && (
              <span className="text-xs text-gray-400">{domains.length} configured</span>
            )}
          </div>
        </div>

        {/* Tab content */}
        {landingTab === "overview" && (
          <AppOverview onGoToAreas={() => setLandingTab("areas")} liveModelConfig={modelConfig} />
        )}
        {landingTab === "areas" && (
          <SubjectAreasPanel
            domains={domains}
            domainsLoading={domainsLoading}
            onOpenDomain={openDomain}
          />
        )}
      </main>
    );
  }

  // ── Domain Workspace ───────────────────────────────────────────────────────
  const domainIcon = DOMAIN_ICONS[activeDomain.domain_id] ?? "📂";
  const currentTab = WORKSPACE_TABS.find(t => t.id === activeTab)!;

  return (
    <DomainContext.Provider value={{ domain: domainCtxState, setDomain: setDomainCtxState }}>
      <PipelineRunProvider>
      <main className="flex-1 flex flex-col bg-gray-50">
        {/* Domain + tab bar */}
        <div className="bg-white border-b border-gray-200 px-4 flex items-center gap-0 min-h-[48px]">
          {/* Back to landing */}
          <button
            onClick={() => { setLandingTab("areas"); closeDomain(); }}
            title="Back to Subject Areas"
            className="flex items-center gap-1.5 mr-3 text-xs font-medium text-gray-400 hover:text-gray-700 py-3 border-r border-gray-100 pr-3 flex-shrink-0"
          >
            ← <span className="hidden sm:inline text-gray-500">Subject Areas</span>
          </button>

          {/* Domain badge */}
          <div className="flex items-center gap-1.5 mr-4 flex-shrink-0 border-r border-gray-100 pr-4 py-3">
            <span className="text-base">{domainIcon}</span>
            <span className="text-xs font-bold text-gray-800">{activeDomain.name}</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${STATUS_COLOR[activeDomain.status ?? "active"] ?? STATUS_COLOR.active}`}>
              {activeDomain.status ?? "active"}
            </span>
          </div>

          {/* Workspace tabs */}
          {WORKSPACE_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => switchTab(t.id)}
              title={t.description}
              className={`group relative flex items-center gap-1.5 px-4 py-3 text-xs font-semibold border-b-2 transition-colors whitespace-nowrap
                ${activeTab === t.id
                  ? "border-blue-600 text-blue-700 bg-blue-50/40"
                  : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
                }`}
            >
              <span>{t.icon}</span>
              <span className="hidden sm:inline">{t.shortLabel}</span>
              {/* Tooltip */}
              <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-52 bg-gray-900 text-white text-[10px] rounded-lg px-3 py-2 leading-snug opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg text-left">
                <strong className="block mb-0.5">{t.label}</strong>
                {t.description}
              </span>
            </button>
          ))}

          {/* Right: search button + active tab badge */}
          <div className="ml-auto flex items-center gap-2 flex-shrink-0">
            {/* Global search button */}
            <button
              onClick={() => { setSearchOpen(true); setSearchQuery(""); setSearchResults([]); setTimeout(() => searchInputRef.current?.focus(), 50); }}
              title="Search documents (⌘K)"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 bg-gray-50 hover:bg-white hover:border-gray-300 text-xs text-gray-500 transition-colors cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <span className="hidden sm:inline">Search docs</span>
              <kbd className="hidden lg:inline text-[10px] bg-gray-200 text-gray-400 px-1 rounded">⌘K</kbd>
            </button>

            {/* Active tab badge */}
            <div className="hidden lg:flex items-center gap-1.5 text-xs text-gray-400">
              <span>{currentTab.icon}</span>
              <span className="font-medium text-gray-600">{currentTab.label}</span>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${currentTab.badgeColor}`}>
                {currentTab.badge}
              </span>
            </div>
          </div>
        </div>

        {/* Module content — domain passed as explicit prop to eliminate context drift */}
        <div className="flex-1">
          {activeTab === "doc"     && <DocIntelligence domain={activeDomain!} />}
          {activeTab === "library" && <DocIntelligence domain={activeDomain!} initialStep="library" />}
          {activeTab === "tower"   && <ControlTower domain={activeDomain!} />}
          {activeTab === "agent"   && <AIAgent domain={activeDomain!} />}
        </div>
      </main>

      {/* ── Global Document Search Overlay ──────────────────────────────── */}
      {searchOpen && activeDomain && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/40 z-40" onClick={() => setSearchOpen(false)} />
          {/* Search panel */}
          <div className="fixed top-16 left-1/2 -translate-x-1/2 w-full max-w-2xl z-50 px-4">
            <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
              {/* Search input */}
              <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
                <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder={`Search ${activeDomain.name} documents…`}
                  className="flex-1 text-sm text-gray-800 placeholder-gray-400 focus:outline-none bg-transparent"
                  autoFocus
                />
                {/* Mode toggle */}
                <div className="flex rounded-lg border border-gray-200 overflow-hidden flex-shrink-0">
                  {(["keyword", "semantic"] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => { setSearchMode(m); setSearchResults([]); }}
                      className={`text-[10px] font-semibold px-2.5 py-1 transition-colors cursor-pointer capitalize ${searchMode === m ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-50"}`}
                    >{m}</button>
                  ))}
                </div>
                <button onClick={() => setSearchOpen(false)} className="text-gray-400 hover:text-gray-600 text-xs flex-shrink-0 cursor-pointer">ESC</button>
              </div>

              {/* Mode hint */}
              <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-100">
                <p className="text-[10px] text-gray-400">
                  {searchMode === "keyword"
                    ? "Keyword — searches filename and full document text"
                    : "Semantic — finds conceptually related content using Vector Search"}
                  {" · "}
                  <span className="font-medium text-gray-600">{activeDomain.name}</span>
                </p>
              </div>

              {/* Results */}
              <div className="max-h-[60vh] overflow-y-auto">
                {searchLoading && (
                  <div className="px-4 py-6 text-center text-sm text-gray-400 animate-pulse">Searching…</div>
                )}
                {!searchLoading && searchQuery && searchResults.length === 0 && (
                  <div className="px-4 py-6 text-center text-sm text-gray-400">No results for &ldquo;{searchQuery}&rdquo;</div>
                )}
                {!searchLoading && !searchQuery && (
                  <div className="px-4 py-6 text-center text-sm text-gray-400">Start typing to search…</div>
                )}
                {searchResults.map((r, i) => (
                  <button
                    key={i}
                    onClick={() => { setViewDocId(r.doc_id); setSearchOpen(false); }}
                    className="w-full text-left px-4 py-3 border-b border-gray-50 hover:bg-blue-50 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-semibold text-gray-900 truncate group-hover:text-blue-700">
                            {r.filename}
                          </span>
                          {r.doc_type && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 flex-shrink-0">
                              {r.doc_type.replace(/_/g, " ")}
                            </span>
                          )}
                        </div>
                        {r.snippet && (
                          <p className="text-[11px] text-gray-500 leading-relaxed line-clamp-2">
                            {r.snippet}
                          </p>
                        )}
                      </div>
                      <span className="text-gray-300 group-hover:text-blue-400 flex-shrink-0 text-xs mt-0.5">↗</span>
                    </div>
                  </button>
                ))}
              </div>

              {searchResults.length > 0 && (
                <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 text-[10px] text-gray-400 text-right">
                  {searchResults.length} result{searchResults.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Document Viewer Panel (opened from search results) ──────────── */}
      {viewDocId && activeDomain && (
        <DocViewerPanel
          docId={viewDocId}
          domainId={activeDomain.domain_id}
          onClose={() => setViewDocId(null)}
        />
      )}
      <PipelineStatusPopup />
      </PipelineRunProvider>
    </DomainContext.Provider>
  );
}

const PIPELINE_STAGES = [
  {
    icon: "📂",
    label: "Source Documents",
    color: "border-sky-400 bg-sky-50",
    text: "text-sky-700",
    items: ["PDFs uploaded to UC Volume", "Emails / SharePoint sync", "ERP exports", "Scanned docs"],
  },
  {
    icon: "🔍",
    label: "Parse & Extract",
    color: "border-violet-400 bg-violet-50",
    text: "text-violet-700",
    items: ["ai_parse_document()", "ai_classify() → 13 doc types", "ai_extract() → typed fields", "Delta: parsed_documents"],
  },
  {
    icon: "🕸",
    label: "Knowledge Graph",
    color: "border-amber-400 bg-amber-50",
    text: "text-amber-700",
    items: ["Entity resolution", "Ontology mapping", "Relationship graph", "Delta: entities + relationships"],
  },
  {
    icon: "🔎",
    label: "Semantic Search",
    color: "border-teal-400 bg-teal-50",
    text: "text-teal-700",
    items: ["Chunk & embed documents", "Databricks Vector Search", "Hybrid retrieval", "Delta Sync Index"],
  },
  {
    icon: "🤖",
    label: "AI Agent",
    color: "border-rose-400 bg-rose-50",
    text: "text-rose-700",
    items: ["UC Function tools", "DBRX / llama-3 reasoning", "Cross-doc Q&A", "MLflow model registry"],
  },
  {
    icon: "📊",
    label: "Govern & Act",
    color: "border-emerald-400 bg-emerald-50",
    text: "text-emerald-700",
    items: ["Unity Catalog lineage", "Action log & reports", "Control Tower UI", "Scheduled pipeline"],
  },
];

const HOW_TO_STEPS = [
  {
    step: "1",
    title: "Upload Documents",
    tab: "Docs tab",
    color: "bg-blue-600",
    desc: "Go to Document Intelligence → upload one or more PDFs. Files land in the Unity Catalog Volume.",
    tip: "Supported: PDF, TXT. Any document type — contracts, invoices, reports, emails.",
  },
  {
    step: "2",
    title: "Run the Pipeline",
    tab: "Docs tab",
    color: "bg-blue-600",
    desc: "Click ▶ Run Pipeline Now in the Document Library panel. The pipeline parses, classifies, extracts fields, builds the knowledge graph, and indexes for search.",
    tip: "Takes ~5–10 min for a batch of 10–20 docs. Also runs automatically nightly at 2 AM UTC.",
  },
  {
    step: "3",
    title: "Explore Control Tower",
    tab: "Control Tower tab",
    color: "bg-green-600",
    desc: "View the incident dashboard, ontology map, supplier risk scores, and take actions. Actions are logged for audit and reporting.",
    tip: "Click any node in the ontology graph to see entity details and relationships.",
  },
  {
    step: "4",
    title: "Ask the AI Agent",
    tab: "AI Agent tab",
    color: "bg-purple-600",
    desc: "Ask natural-language questions like 'Which restaurants received the recalled product?' or 'What is our financial exposure?' The agent reasons across all documents and structured tables.",
    tip: "Suggested questions appear at the top of the chat. The agent cites specific lot numbers, dates, and amounts.",
  },
  {
    step: "5",
    title: "Add New Subject Areas",
    tab: "Home → New Subject Area",
    color: "bg-gray-700",
    desc: "Return to the Subject Area selector and click + New Subject Area to run the setup wizard for Compliance, Procurement, HR, or any custom domain.",
    tip: "The wizard uses AI to suggest classification labels and extraction schemas for your domain.",
  },
];

const CONNECTORS = [
  // Built-in
  {
    name: "Manual Upload",
    category: "Built-in",
    icon: "⬆️",
    desc: "Upload files directly from the app UI. Stored in Unity Catalog Volumes.",
    status: "live",
    link: null,
  },
  // Lakeflow Connect (native Databricks)
  {
    name: "SharePoint / OneDrive",
    category: "Lakeflow Connect",
    icon: "📎",
    desc: "Sync documents from Microsoft SharePoint or OneDrive into Unity Catalog.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/sharepoint.html",
  },
  {
    name: "Salesforce",
    category: "Lakeflow Connect",
    icon: "☁️",
    desc: "Ingest Salesforce records (Opportunities, Cases, Contracts) into Delta tables.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/salesforce.html",
  },
  {
    name: "ServiceNow",
    category: "Lakeflow Connect",
    icon: "🔧",
    desc: "Pull incident, change, and CMDB records from ServiceNow.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/servicenow.html",
  },
  {
    name: "Google Drive",
    category: "Lakeflow Connect",
    icon: "📁",
    desc: "Sync documents and spreadsheets from Google Drive into UC Volumes.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/google-drive.html",
  },
  // Cloud storage / Auto Loader
  {
    name: "Azure Blob / ADLS",
    category: "Auto Loader",
    icon: "🔵",
    desc: "Auto Loader incrementally ingests files as they arrive in Azure Data Lake Storage.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/cloud-object-storage/auto-loader/index.html",
  },
  {
    name: "AWS S3",
    category: "Auto Loader",
    icon: "🟠",
    desc: "Auto Loader watches S3 prefixes and processes new files automatically.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/cloud-object-storage/auto-loader/index.html",
  },
  {
    name: "Google Cloud Storage",
    category: "Auto Loader",
    icon: "🔴",
    desc: "Auto Loader for GCS buckets — incrementally process new documents.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/cloud-object-storage/auto-loader/index.html",
  },
  // Email / Messaging
  {
    name: "Outlook / Office 365",
    category: "Email & Messaging",
    icon: "📧",
    desc: "Use Microsoft Graph API or Logic Apps to route emails + attachments to UC Volumes.",
    status: "partner",
    link: "https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview",
  },
  {
    name: "Gmail",
    category: "Email & Messaging",
    icon: "📬",
    desc: "Pull emails and attachments via Gmail API or Fivetran Gmail connector.",
    status: "partner",
    link: "https://fivetran.com/docs/connectors/applications/gmail",
  },
  // ERP / Enterprise
  {
    name: "SAP",
    category: "ERP",
    icon: "🏢",
    desc: "Lakeflow Connect SAP connector for purchase orders, invoices, and master data.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/sap.html",
  },
  {
    name: "Workday",
    category: "ERP",
    icon: "👥",
    desc: "Ingest Workday HR, Finance, and Procurement data via Lakeflow Connect.",
    status: "available",
    link: "https://docs.databricks.com/en/ingestion/lakeflow-connect/workday.html",
  },
];

const CONNECTOR_STATUS_STYLE: Record<string, { badge: string; label: string }> = {
  live:      { badge: "bg-green-100 text-green-700",  label: "Live" },
  available: { badge: "bg-blue-100 text-blue-700",    label: "Available" },
  partner:   { badge: "bg-purple-100 text-purple-700",label: "Partner" },
};

// ── Subject Areas Panel (standalone tab) ────────────────────────────────────
function SubjectAreasPanel({
  domains,
  domainsLoading,
  onOpenDomain,
}: {
  domains: DomainInfo[];
  domainsLoading: boolean;
  onOpenDomain: (d: DomainInfo) => void;
}) {
  return (
    <div className="flex-1 bg-gray-50 p-6 overflow-auto">
      <div className="max-w-6xl mx-auto">
        <div className="mb-6">
          <h2 className="text-xl font-bold text-gray-900">Subject Areas</h2>
          <p className="text-sm text-gray-500 mt-1">
            Select a subject area to open its workspace, or configure a new one.
            Each subject area has its own document pipeline, ontology, and AI agent.
          </p>
        </div>

        {domainsLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-48 bg-white rounded-xl border-2 border-gray-100 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {domains.map(d => {
              const icon = DOMAIN_ICONS[d.domain_id] ?? "📂";
              const statusBadge = STATUS_COLOR[d.status ?? "active"] ?? STATUS_COLOR.active;
              return (
                <button
                  key={d.domain_id}
                  onClick={() => onOpenDomain(d)}
                  disabled={d.status === "configuring"}
                  className={`group text-left bg-white rounded-xl border-2 p-6 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500
                    ${d.status === "configuring"
                      ? "border-gray-100 opacity-60 cursor-not-allowed"
                      : "border-gray-200 hover:border-blue-400 hover:shadow-xl hover:-translate-y-1 cursor-pointer"
                    }`}
                >
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-4xl">{icon}</span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${statusBadge}`}>
                      {d.status ?? "active"}
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-gray-900 mb-1.5 group-hover:text-blue-700">
                    {d.name}
                  </h3>
                  <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">
                    {d.description || "Document Intelligence subject area"}
                  </p>
                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-[10px] text-gray-400">
                      {d.doc_count != null && d.doc_count > 0 ? `${d.doc_count} docs` : ""}
                    </span>
                    {d.status !== "configuring" ? (
                      <span className="text-xs font-semibold text-blue-600 group-hover:text-blue-800 flex items-center gap-1">
                        Open workspace <span className="group-hover:translate-x-1 transition-transform inline-block">→</span>
                      </span>
                    ) : (
                      <span className="text-[10px] text-yellow-600 font-medium">Setting up…</span>
                    )}
                  </div>
                </button>
              );
            })}

            {/* Add New Subject Area */}
            <Link
              href="/setup"
              className="group text-left bg-white rounded-xl border-2 border-dashed border-gray-200 p-6 hover:border-blue-400 hover:shadow-xl hover:-translate-y-1 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 flex flex-col items-center justify-center min-h-[180px]"
            >
              <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mb-3 group-hover:bg-blue-100 transition-colors">
                <span className="text-2xl font-bold text-blue-500">+</span>
              </div>
              <h3 className="text-sm font-bold text-gray-700 group-hover:text-blue-700 mb-1.5 text-center">
                New Subject Area
              </h3>
              <p className="text-xs text-gray-400 text-center leading-relaxed">
                Compliance, Procurement, HR, Finance, or any custom domain
              </p>
            </Link>
          </div>
        )}

        {/* Platform info strip */}
        <div className="mt-8 bg-white rounded-xl border border-gray-200 px-5 py-4 flex flex-wrap gap-x-8 gap-y-2 text-xs text-gray-500">
          <span className="font-semibold text-gray-700 self-center">HOW IT WORKS</span>
          {["Upload documents", "AI parses & classifies", "Fields extracted", "Ontology built", "Vector index created", "AI Agent answers questions"].map((s, i) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className="w-4 h-4 rounded-full bg-blue-100 text-blue-700 font-bold text-[10px] flex items-center justify-center flex-shrink-0">{i + 1}</span>
              {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function AppOverview({ onGoToAreas, liveModelConfig }: {
  onGoToAreas: () => void;
  liveModelConfig?: { agent_model: string; embed_model: string; setup_model: string; fallback_chain: string[]; available_models: string[]; resolved_live: boolean; } | null;
}) {
  const connectorCategories = Array.from(new Set(CONNECTORS.map(c => c.category)));

  return (
    <div className="flex-1 bg-gray-50 p-6 overflow-auto">
      <div className="max-w-6xl mx-auto space-y-10">

        {/* Hero */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-start justify-between gap-4 mb-5">
            <div>
              <h1 className="text-2xl font-bold text-gray-900 mb-1">
                Multi-Domain Document Intelligence Platform
              </h1>
              <p className="text-sm text-gray-500 max-w-2xl">
                Transforms unstructured documents into a governed semantic knowledge layer —
                combining Document AI, Ontology, Vector Search, and Databricks AI Agents (FMAPIs) on the Databricks Lakehouse.
              </p>
              <div className="flex flex-wrap gap-2 mt-3">
                {["Unity Catalog", "Delta Lake", "AI Functions", "Vector Search", "Databricks AI Agents", "Auto Loader"].map(t => (
                  <span key={t} className="text-[10px] font-semibold px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">{t}</span>
                ))}
              </div>
            </div>
            <div className="hidden lg:flex flex-col items-end gap-3 flex-shrink-0">
              <div className="grid grid-cols-3 gap-3">
                {[
                  { v: "5",   l: "Pipeline Stages" },
                  { v: "3",   l: "App Modules" },
                  { v: "12+", l: "Connectors" },
                ].map(({ v, l }) => (
                  <div key={l} className="text-center bg-gray-50 rounded-lg px-4 py-3">
                    <p className="text-2xl font-bold text-gray-800">{v}</p>
                    <p className="text-[10px] text-gray-400 font-medium">{l}</p>
                  </div>
                ))}
              </div>
              <button
                onClick={onGoToAreas}
                className="text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
              >
                📂 Go to Subject Areas →
              </button>
            </div>
          </div>

          {/* Mental model */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { q: "What happened?",     a: "Documents", icon: "📄", color: "border-blue-200 bg-blue-50",    tc: "text-blue-700" },
              { q: "What does it mean?", a: "Ontology",  icon: "🕸", color: "border-amber-200 bg-amber-50",  tc: "text-amber-700" },
              { q: "What should we do?", a: "AI Agent",  icon: "🤖", color: "border-purple-200 bg-purple-50", tc: "text-purple-700" },
            ].map(({ q, a, icon, color, tc }) => (
              <div key={q} className={`rounded-lg border p-4 ${color}`}>
                <p className="text-xl mb-1">{icon}</p>
                <p className="text-xs text-gray-500 italic mb-0.5">&ldquo;{q}&rdquo;</p>
                <p className={`text-sm font-bold ${tc}`}>{a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Pipeline Architecture */}
        <div>
          <h2 className="text-base font-bold text-gray-800 mb-3">Pipeline Architecture</h2>
          <div className="relative">
            {/* Flow stages */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {PIPELINE_STAGES.map((stage, i) => (
                <div key={stage.label} className="relative">
                  <div className={`rounded-xl border-2 p-4 h-full ${stage.color}`}>
                    <p className="text-2xl mb-2">{stage.icon}</p>
                    <p className={`text-xs font-bold mb-2 ${stage.text}`}>{stage.label}</p>
                    <ul className="space-y-1">
                      {stage.items.map(item => (
                        <li key={item} className="text-[10px] text-gray-600 flex items-start gap-1">
                          <span className="mt-0.5 flex-shrink-0 opacity-50">·</span>
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                  {/* Arrow connector */}
                  {i < PIPELINE_STAGES.length - 1 && (
                    <div className="hidden lg:flex absolute -right-2 top-1/2 -translate-y-1/2 z-10 items-center justify-center w-4">
                      <span className="text-gray-300 text-lg font-bold">›</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Databricks components strip */}
          <div className="mt-3 bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap gap-x-6 gap-y-1">
            <span className="text-[10px] font-semibold text-gray-400 self-center">DATABRICKS COMPONENTS</span>
            {[
              ["UC Volumes", "Storage"],
              ["ai_parse_document", "Parse"],
              ["ai_classify / ai_extract", "Classify & Extract"],
              ["Delta Lake", "Persistence"],
              ["Vector Search", "Semantic Index"],
              ["Foundation Model APIs (FMAPIs)", "LLM"],
              ["Databricks AI Agents", "Agent"],
              ["Unity Catalog", "Governance"],
              ["MLflow", "Tracking"],
            ].map(([name, layer]) => (
              <div key={name} className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-gray-700">{name}</span>
                <span className="text-[9px] text-gray-400">{layer}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Batch Operations */}
        <div>
          <h2 className="text-base font-bold text-gray-800 mb-1">Batch Operations</h2>
          <p className="text-xs text-gray-500 mb-4">
            Three Databricks Jobs drive all compute. Understanding when and how to run each keeps the platform healthy.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              {
                name: "Process New Documents",
                schedule: "Nightly · 2 AM UTC",
                trigger: "Automatic + UI button",
                scheduleColor: "bg-green-100 text-green-700",
                icon: "▶",
                iconBg: "bg-green-50 text-green-600",
                when: "Run whenever new documents are uploaded. Triggered automatically by the nightly schedule or instantly via the Run Pipeline Now button in the Document Intelligence tab.",
                tasks: ["Clean pipeline tables", "Parse PDFs (ai_parse_document)", "Extract content", "Classify & extract fields (IDP)", "Build ontology graph", "Update Vector Search index", "Re-register AI Agent"],
                note: "Safe to run multiple times — idempotent.",
              },
              {
                name: "Setup New Domain",
                schedule: "On-demand only",
                trigger: "Setup wizard Step 6",
                scheduleColor: "bg-blue-100 text-blue-700",
                icon: "⚙",
                iconBg: "bg-blue-50 text-blue-600",
                when: "Runs once per new subject area. Triggered automatically by clicking Provision in the setup wizard (Step 6). Creates the Unity Catalog schema, document Volume, and Delta tables for the domain.",
                tasks: ["Bootstrap platform registry", "Create domain UC schema", "Create raw/ontology/vectors/agents schemas", "Create UC Volume for documents", "Seed domain_configs table"],
                note: "Run only once per domain. Re-running is safe.",
              },
              {
                name: "Full Pipeline (Reset)",
                schedule: "Manual only",
                trigger: "Databricks Jobs UI",
                scheduleColor: "bg-amber-100 text-amber-700",
                icon: "⟳",
                iconBg: "bg-amber-50 text-amber-600",
                when: "Use only for a full rebuild — regenerates synthetic data, rebuilds all tables from scratch. Not needed for normal operations. Run from Databricks workspace → Jobs → DocIntelligence — Full Pipeline.",
                tasks: ["All Process New Documents tasks", "Regenerate synthetic corpus", "Rebuild structured tables", "Generate PDFs", "Run demo scenario"],
                note: "Includes synthetic data generation — do not schedule.",
              },
            ].map(job => (
              <div key={job.name} className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3">
                <div className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-base font-bold flex-shrink-0 ${job.iconBg}`}>
                    {job.icon}
                  </div>
                  <div>
                    <p className="text-sm font-bold text-gray-900 leading-tight">{job.name}</p>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${job.scheduleColor}`}>{job.schedule}</span>
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">{job.trigger}</span>
                    </div>
                  </div>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">{job.when}</p>
                <div>
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Tasks in order</p>
                  <ol className="space-y-0.5">
                    {job.tasks.map((t, i) => (
                      <li key={t} className="text-[10px] text-gray-500 flex items-start gap-1.5">
                        <span className="text-gray-300 font-mono flex-shrink-0">{i + 1}.</span>
                        {t}
                      </li>
                    ))}
                  </ol>
                </div>
                <p className="text-[10px] text-gray-400 italic border-t border-gray-100 pt-2">{job.note}</p>
              </div>
            ))}
          </div>

          {/* New domain / connector guidance */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
              <p className="text-xs font-semibold text-blue-800 mb-2">Adding a New Subject Area</p>
              <ol className="space-y-1 text-xs text-blue-700">
                {["Go to Home → Subject Areas → + New Subject Area.",
                  "Complete the 7-step wizard: name, doc types (with ai_classify descriptions), extraction schema, ontology entities, system prompt, provision.",
                  "The wizard triggers the Setup New Domain job automatically at Step 6.",
                  "Once the job completes, click Activate — the new workspace appears in the Subject Areas grid.",
                  "Upload documents and click Run Pipeline Now to process them."
                ].map((s, i) => (
                  <li key={i} className="flex gap-1.5"><span className="font-bold flex-shrink-0">{i + 1}.</span>{s}</li>
                ))}
              </ol>
            </div>
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
              <p className="text-xs font-semibold text-emerald-800 mb-2">Adding a New Connector</p>
              <p className="text-[10px] text-emerald-700 font-semibold mb-1.5">Lakeflow Connect (SharePoint, Salesforce, ServiceNow)</p>
              <ol className="space-y-0.5 text-xs text-emerald-700 mb-3">
                {["Catalog Explorer → External Data → Connections → Create.",
                  "Target: jai_docintel.raw.documents volume.",
                  "Run or schedule the connector sync.",
                  "Click Run Pipeline Now — Auto Loader picks up new files."
                ].map((s, i) => <li key={i} className="flex gap-1.5"><span className="font-bold">{i + 1}.</span>{s}</li>)}
              </ol>
              <p className="text-[10px] text-emerald-700 font-semibold mb-1.5">Auto Loader (Azure Blob, S3, GCS)</p>
              <ol className="space-y-0.5 text-xs text-emerald-700">
                {["Configure cloud storage credential in Unity Catalog.",
                  "Update source_volume_path in the workflow_parse task (databricks.yml or job parameter).",
                  "Run docintel_process_docs job."
                ].map((s, i) => <li key={i} className="flex gap-1.5"><span className="font-bold">{i + 1}.</span>{s}</li>)}
              </ol>
            </div>
          </div>
        </div>

        {/* Architecture Capabilities & FMAPI Configuration */}
        <div>
          <h2 className="text-base font-bold text-gray-800 mb-1">Architecture Capabilities & Model Configuration</h2>
          <p className="text-xs text-gray-500 mb-4">
            What each pipeline stage does, which Databricks services it uses, and which Foundation Model API endpoint it calls.
          </p>

          {/* Stage capability table */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-4">
            <div className="grid grid-cols-4 bg-gray-50 border-b border-gray-200 px-4 py-2 text-[10px] font-bold text-gray-500 uppercase tracking-wide">
              <span>Stage</span>
              <span>Notebook</span>
              <span>Databricks Services</span>
              <span>FMAPI / AI Function</span>
            </div>
            {[
              { stage: "1 · Document Ingest",    nb: "01_parse_documents.py",          svc: "UC Volumes, Auto Loader, Delta Lake",                   api: "ai_parse_document()" },
              { stage: "2 · Content Extraction", nb: "02_extract_document_content.py", svc: "Delta Lake",                                            api: "ai_extract() SQL function" },
              { stage: "3 · IDP Pipeline",       nb: "03_idp_pipeline.py",             svc: "Delta Lake (Silver), SQL Warehouse",                    api: "ai_classify() + ai_extract()" },
              { stage: "4 · Ontology Mapping",   nb: "04_ontology_mapping.py",         svc: "Delta entities + relationships tables, SQL Warehouse",  api: "ai_extract() (entity/rel extraction)" },
              { stage: "5 · Vector Search",      nb: "05_vector_search.py",            svc: "Vector Search endpoint, Delta Sync Index",              api: "databricks-gte-large-en (embeddings)" },
              { stage: "6 · AI Agent",           nb: "06_agent.py",                    svc: "UC Functions (6 tools), MLflow, Model Serving",         api: (liveModelConfig?.agent_model ?? "databricks-claude-sonnet-4-5") + " (LLM)" },
              { stage: "Setup · Domain Provision",nb: "00_setup.py",                   svc: "Unity Catalog schema, Volume creation",                 api: "None" },
            ].map((row, i) => (
              <div key={row.stage} className={`grid grid-cols-4 px-4 py-2.5 text-xs border-b border-gray-100 last:border-0 ${i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}`}>
                <span className="font-semibold text-gray-800">{row.stage}</span>
                <span className="font-mono text-[10px] text-gray-500">{row.nb}</span>
                <span className="text-gray-600 text-[11px]">{row.svc}</span>
                <span className="font-mono text-[10px] text-blue-700">{row.api}</span>
              </div>
            ))}
          </div>

          {/* FMAPI configuration */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-sm font-bold text-gray-800">Foundation Model API (FMAPI) Endpoints</p>
              {liveModelConfig && (
                <span className={`text-[9px] font-semibold px-2 py-0.5 rounded-full ${liveModelConfig.resolved_live ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                  {liveModelConfig.resolved_live ? "● Live" : "● Cached"}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-4">Three model endpoints are used. Each is configured in a different location.</p>
            <div className="space-y-3">
              {[
                {
                  role:     "agent",
                  endpoint: liveModelConfig?.agent_model ?? "databricks-claude-sonnet-4-5",
                  use:      "AI Agent — answers natural-language questions across documents and structured tables",
                  location: "app/backend/app.yaml → DOCINTEL_AGENT_MODEL",
                  how:      "Edit the value in app.yaml and redeploy the app.",
                  alts:     (liveModelConfig?.fallback_chain ?? ["databricks-claude-sonnet-4-5","databricks-claude-haiku-4-5","databricks-gpt-5-4"]).filter(m => m !== (liveModelConfig?.agent_model ?? "databricks-claude-sonnet-4-5")).slice(0,3),
                  color:    "border-purple-200 bg-purple-50",
                  badge:    "bg-purple-100 text-purple-800",
                },
                {
                  role:     "embed",
                  endpoint: liveModelConfig?.embed_model ?? "databricks-gte-large-en",
                  use:      "Document embeddings — converts text chunks to vectors for semantic search",
                  location: "notebooks/05_vector_search.py → EMBED_MODEL (line 60)",
                  how:      "Edit the notebook variable, then re-run the vector_search pipeline task.",
                  alts:     ["databricks-bge-large-en", "databricks-e5-large-v2"],
                  color:    "border-teal-200 bg-teal-50",
                  badge:    "bg-teal-100 text-teal-800",
                },
                {
                  role:     "setup",
                  endpoint: liveModelConfig?.setup_model ?? "databricks-meta-llama-3-3-70b-instruct",
                  use:      "Setup wizard AI suggestions — generates document type labels and extraction schemas",
                  location: "app/backend/platform_routes.py → ai_query() call",
                  how:      "Edit the model name string in platform_routes.py and redeploy.",
                  alts:     ["databricks-claude-sonnet-4-5", "databricks-dbrx-instruct"],
                  color:    "border-blue-200 bg-blue-50",
                  badge:    "bg-blue-100 text-blue-800",
                },
              ].map(m => (
                <div key={m.role} className={`rounded-lg border p-4 ${m.color}`}>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full font-mono ${m.badge}`}>{m.endpoint}</span>
                    <span className="text-[10px] text-gray-500 text-right leading-tight">{m.use}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-[11px]">
                    <div>
                      <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">Configured in</p>
                      <p className="font-mono text-gray-700 text-[10px]">{m.location}</p>
                    </div>
                    <div>
                      <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">How to change</p>
                      <p className="text-gray-600 text-[10px]">{m.how}</p>
                    </div>
                  </div>
                  {m.alts.length > 0 && (
                    <div className="mt-2">
                      <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Alternative endpoints</p>
                      <div className="flex flex-wrap gap-1.5">
                        {m.alts.map(a => <span key={a} className="text-[9px] font-mono bg-white/60 border border-gray-200 px-1.5 py-0.5 rounded text-gray-600">{a}</span>)}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            {/* Stage table row fix: stage 6 AI Agent now shows the resolved model */}
          </div>
        </div>

        {/* How to Use */}
        <div>
          <h2 className="text-base font-bold text-gray-800 mb-3">How to Use This App</h2>
          <div className="space-y-3">
            {HOW_TO_STEPS.map(step => (
              <div key={step.step} className="bg-white rounded-xl border border-gray-200 p-4 flex gap-4">
                <div className={`w-8 h-8 rounded-full ${step.color} text-white text-sm font-bold flex items-center justify-center flex-shrink-0`}>
                  {step.step}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-sm font-bold text-gray-900">{step.title}</p>
                    <span className="text-[10px] font-semibold px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full">{step.tab}</span>
                  </div>
                  <p className="text-sm text-gray-600">{step.desc}</p>
                  <p className="text-xs text-gray-400 mt-1 italic">💡 {step.tip}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Connectors */}
        <div>
          <h2 className="text-base font-bold text-gray-800 mb-1">Available Data Source Connectors</h2>
          <p className="text-xs text-gray-500 mb-4">
            Connect any document or data source to the platform. Ingested data lands in Unity Catalog and is automatically picked up by the nightly pipeline.
          </p>
          <div className="space-y-6">
            {connectorCategories.map(cat => (
              <div key={cat}>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">{cat}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {CONNECTORS.filter(c => c.category === cat).map(conn => {
                    const st = CONNECTOR_STATUS_STYLE[conn.status] ?? CONNECTOR_STATUS_STYLE.available;
                    return (
                      <div key={conn.name} className="bg-white rounded-xl border border-gray-200 p-4 hover:border-blue-300 transition-colors">
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-lg">{conn.icon}</span>
                            <span className="text-sm font-bold text-gray-800">{conn.name}</span>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${st.badge}`}>
                            {st.label}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 leading-relaxed mb-2">{conn.desc}</p>
                        {/* Implementation steps for Lakeflow Connect */}
                        {conn.category === "Lakeflow Connect" && (
                          <div className="mb-2 bg-blue-50 rounded-lg p-2.5">
                            <p className="text-[9px] font-bold text-blue-600 uppercase tracking-wide mb-1">Setup steps</p>
                            <ol className="space-y-0.5 text-[10px] text-blue-700">
                              {["Catalog Explorer → External Data → Connections → Create.",
                                "Set target to jai_docintel.raw.documents volume.",
                                "Run or schedule the connector sync.",
                                "Click Run Pipeline Now in the Docs tab."
                              ].map((s, i) => (
                                <li key={i} className="flex gap-1"><span className="font-bold">{i + 1}.</span>{s}</li>
                              ))}
                            </ol>
                          </div>
                        )}
                        {/* Implementation steps for Auto Loader */}
                        {conn.category === "Auto Loader" && (
                          <div className="mb-2 bg-emerald-50 rounded-lg p-2.5">
                            <p className="text-[9px] font-bold text-emerald-600 uppercase tracking-wide mb-1">Setup steps</p>
                            <ol className="space-y-0.5 text-[10px] text-emerald-700">
                              {["Configure storage credential in Unity Catalog.",
                                "Update source_volume_path in databricks.yml (workflow_parse task).",
                                "Run the docintel_process_docs job."
                              ].map((s, i) => (
                                <li key={i} className="flex gap-1"><span className="font-bold">{i + 1}.</span>{s}</li>
                              ))}
                            </ol>
                          </div>
                        )}
                        {conn.link ? (
                          <a
                            href={conn.link}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800"
                          >
                            Setup docs → 
                          </a>
                        ) : (
                          <span className="text-xs text-green-600 font-semibold">✓ Already configured</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 bg-blue-50 border border-blue-200 rounded-xl p-4">
            <p className="text-xs font-semibold text-blue-800 mb-1">Adding a new connector</p>
            <p className="text-xs text-blue-700">
              Once a connector syncs files into a Unity Catalog Volume (or Delta table), add the Volume path to the pipeline job parameters and run ▶ Run Pipeline Now from the Document Intelligence tab. The pipeline will pick up all new documents automatically.
            </p>
          </div>
        </div>

        {/* PRD Mental Model Footer */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-bold text-gray-800 mb-3">Platform Design Philosophy</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-gray-600">
            <div>
              <p className="font-semibold text-gray-800 mb-1">Not OCR. Not RAG.</p>
              <p>The goal is a semantic operational knowledge layer — not just document text retrieval. Every document becomes part of a business ontology with typed entities, relationships, and governed metadata.</p>
            </div>
            <div>
              <p className="font-semibold text-gray-800 mb-1">Governed by Lakehouse</p>
              <p>All data lives in Unity Catalog with lineage, permissions, and classification. The same governance that applies to structured Delta tables applies to every document and extracted entity.</p>
            </div>
            <div>
              <p className="font-semibold text-gray-800 mb-1">Multi-Domain by Design</p>
              <p>The same pipeline that processes supply chain documents can be configured for Compliance, HR, Procurement, or any domain. Each Subject Area gets its own UC schemas, AI prompts, and agent tools.</p>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
