"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { getApiBaseUrl } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  tools_used?: number;
  fallback?: boolean;
}

interface IncidentSummary {
  incident_id: string;
  incident_type: string;
  title: string;
  status: string;
  severity: string;
  opened_date: string;
  primary_entity_label: string;
  financial_exposure_usd: number;
  affected_count: number;
  affected_label: string;
}

const SEV_COLOR: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-300",
  high:     "bg-orange-100 text-orange-800 border-orange-300",
  medium:   "bg-amber-100 text-amber-800 border-amber-300",
  low:      "bg-gray-100 text-gray-700 border-gray-200",
};

const STATUS_ICON: Record<string, string> = {
  active: "🔴", investigating: "🟡", resolved: "✅", escalated: "⚠️",
};

// Suggested questions keyed by incident type / id
function suggestedQuestions(inc: IncidentSummary | null): string[] {
  if (!inc) return [
    "Summarise all open incidents and their financial exposure.",
    "Which supplier has the highest risk score across all incidents?",
    "What documents are linked to the most recent incident?",
  ];
  if (inc.incident_type === "recall" || inc.incident_id.startsWith("RCL")) return [
    `Which restaurants received product from the shipment in ${inc.incident_id}?`,
    `What is the total financial exposure from ${inc.incident_id}?`,
    `Which contract terms make ${inc.primary_entity_label} liable for this recall?`,
    `What caused the quality failure linked to ${inc.incident_id}?`,
    `How does ${inc.primary_entity_label}'s risk score compare to other suppliers?`,
    "Which distribution centers have the highest cold chain failure rate?",
  ];
  if (inc.incident_type === "food_safety" || inc.incident_id.startsWith("FSE")) return [
    `What products are implicated in the allergen mislabelling for ${inc.incident_id}?`,
    `Which restaurant locations received affected product from ${inc.primary_entity_label}?`,
    `What corrective actions have been logged for ${inc.incident_id}?`,
    `What documents describe the QA failure at ${inc.primary_entity_label}?`,
    `What is the FDA notification status for ${inc.incident_id}?`,
  ];
  if (inc.incident_type === "audit" || inc.incident_id.startsWith("AUD")) return [
    `What temperature violations were found during the audit of ${inc.primary_entity_label}?`,
    `What are the corrective action requirements from ${inc.incident_id}?`,
    `Which shipments from ${inc.primary_entity_label} are at risk due to cold chain failure?`,
    `What SLA terms apply to temperature compliance for ${inc.primary_entity_label}?`,
    `What documents were reviewed during the ${inc.incident_id} audit?`,
  ];
  if (inc.incident_type === "contract" || inc.incident_id.startsWith("CTR")) return [
    `What are the disputed terms in the ${inc.primary_entity_label} contract?`,
    `What financial penalties apply if ${inc.primary_entity_label} breaches SLA?`,
    `What documents describe the contract dispute in ${inc.incident_id}?`,
    `What is the renewal timeline for the ${inc.primary_entity_label} agreement?`,
    `Which performance metrics triggered the dispute in ${inc.incident_id}?`,
  ];
  return [
    `Summarise the key facts about incident ${inc.incident_id}.`,
    `What documents are linked to ${inc.incident_id}?`,
    `What actions have been logged for ${inc.incident_id}?`,
    `What is the financial exposure for ${inc.incident_id}?`,
    `Who is the primary entity involved in ${inc.incident_id}?`,
  ];
}

const COMPLIANCE_SUGGESTED = [
  "What regulations apply to Georgia? Cite authoritative sources.",
  "Which stores have open compliance findings from inspections?",
  "Summarize all compliance correspondence for this quarter.",
  "What changed in food safety regulations this month?",
  "Are there any jurisdictional conflicts requiring legal review?",
  "What are the open action items, owners, and deadlines across all documents?",
];

// Detect structured copilot sections in text
function hasCopilotSections(text: string): boolean {
  return /Facts\s*[:：]/i.test(text) || /Risks\s*[:：]/i.test(text) || /Next\s+Steps\s*[:：]/i.test(text);
}

// Parse structured response into named sections
function parseSections(text: string): Record<string, string> {
  const headers = ["Facts", "Sources", "Risks", "Open Questions", "Recommended Next Steps"];
  const pattern = new RegExp(
    `(${headers.map(h => h.replace(/\s+/g, "\\s+")).join("|")})\\s*[:：]`,
    "gi"
  );
  const matches: { key: string; start: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    matches.push({ key: m[1].toLowerCase().replace(/\s+/g, "_"), start: m.index + m[0].length });
  }
  const result: Record<string, string> = {};
  matches.forEach((match, i) => {
    const end = i + 1 < matches.length ? matches[i + 1].start - matches[i + 1].key.length - 5 : text.length;
    result[match.key] = text.slice(match.start, end).trim();
  });
  return result;
}

// Inline structured response component for agent page
function AgentStructuredResponse({ content }: { content: string }) {
  const sections = parseSections(content);
  const attorneyReview = /attorney review recommended/i.test(content);
  const sectionDefs = [
    { key: "facts",                    label: "Facts",                  icon: "📋", bg: "bg-blue-50",   border: "border-blue-100",   text: "text-blue-800",   head: "text-blue-600" },
    { key: "sources",                  label: "Sources",                icon: "📂", bg: "bg-green-50",  border: "border-green-100",  text: "text-green-800",  head: "text-green-600" },
    { key: "risks",                    label: "Risks",                  icon: "⚠️", bg: "bg-red-50",    border: "border-red-100",    text: "text-red-800",    head: "text-red-600" },
    { key: "open_questions",           label: "Open Questions",         icon: "❓", bg: "bg-amber-50",  border: "border-amber-100",  text: "text-amber-800",  head: "text-amber-600" },
    { key: "recommended_next_steps",   label: "Recommended Next Steps", icon: "✅", bg: "bg-indigo-50", border: "border-indigo-100", text: "text-indigo-800", head: "text-indigo-600" },
  ];
  const hasAny = sectionDefs.some(s => sections[s.key]?.trim());
  if (!hasAny) return <pre className="whitespace-pre-wrap font-sans text-sm">{content}</pre>;
  return (
    <div className="space-y-2.5">
      {attorneyReview && (
        <div className="flex items-center gap-2 bg-red-600 text-white text-xs font-semibold px-3 py-2 rounded-lg">
          <span>⚖️</span> Attorney Review Recommended
        </div>
      )}
      {sectionDefs.map(sec => {
        const txt = sections[sec.key];
        if (!txt?.trim()) return null;
        return (
          <div key={sec.key} className={`${sec.bg} ${sec.border} border rounded-lg p-3`}>
            <div className={`text-[10px] font-bold uppercase tracking-wider ${sec.head} mb-1.5 flex items-center gap-1`}>
              <span>{sec.icon}</span><span>{sec.label}</span>
            </div>
            <div className={`text-xs ${sec.text} whitespace-pre-wrap leading-relaxed`}>{txt}</div>
          </div>
        );
      })}
    </div>
  );
}

function nowStamp() {
  return new Date().toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export default function AgentPage({ domain: domainProp }: { domain?: import("@/context/DomainContext").DomainInfo }) {
  const { domain: domainCtx } = useDomain();
  const domain = domainProp ?? domainCtx;
  const domainId   = domain?.domain_id || "supply_chain";
  const domainName = domain?.name || "Supply Chain";
  const domainParam = `domain_id=${encodeURIComponent(domainId)}`;
  const isSupplyChain = domainId === "supply_chain";

  // ── Incident state (supply chain only) ────────────────────────────────────
  const [incidents,        setIncidents]        = useState<IncidentSummary[]>([]);
  const [activeIncidentId, setActiveIncidentId] = useState<string>("");
  const activeIncident = incidents.find(i => i.incident_id === activeIncidentId) ?? null;

  useEffect(() => {
    if (!isSupplyChain) return;
    fetch(`/api/docintel/incidents?${domainParam}`)
      .then(r => r.json())
      .then(d => {
        const list: IncidentSummary[] = d.incidents ?? [];
        setIncidents(list);
        const first = list.find(i => i.status === "active") ?? list[0];
        if (first) setActiveIncidentId(first.incident_id);
      })
      .catch(() => {});
  }, [domainParam, isSupplyChain]);

  // ── Saved copilot prompt (all domains) ────────────────────────────────────
  const [savedPromptSnippet, setSavedPromptSnippet] = useState<string | null>(null);
  useEffect(() => {
    const base = getApiBaseUrl();
    fetch(`${base}/api/docintel/copilot-prompt?domain_id=${domainId}`)
      .then(r => r.json())
      .then(d => { if (d.prompt) setSavedPromptSnippet(d.prompt.slice(0, 120)); })
      .catch(() => {});
  }, [domainId]);

  // Reset chat when incident / domain changes
  const welcomeMsg = useCallback((): Message => ({
    role: "assistant",
    content: isSupplyChain
      ? (activeIncidentId
          ? `I'm the ${domainName} AI assistant focused on incident **${activeIncidentId}**. Ask me any question about this incident — documents, entities, exposure, corrective actions, or liability.`
          : `I'm the ${domainName} AI assistant. Ask me any operational question.`)
      : `I'm the ${domainName} AI assistant. I answer questions grounded in your parsed document library. Every answer cites its source documents.`,
    timestamp: nowStamp(),
  }), [domainName, activeIncidentId, isSupplyChain]);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input,    setInput]    = useState("");
  const [loading,  setLoading]  = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Re-initialise chat when domain or incident changes
  useEffect(() => {
    setMessages([welcomeMsg()]);
  }, [welcomeMsg]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const SUGGESTED = (() => {
    // 1. Always prefer domain-configured suggested questions
    try {
      if (domain?.suggested_questions) {
        const parsed = JSON.parse(domain.suggested_questions as string);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed as string[];
      }
    } catch {}
    // 2. Fallback: supply chain gets incident-specific questions; others get generic
    if (isSupplyChain) return suggestedQuestions(activeIncident);
    return [
      `Summarize key findings across all ${domainName} documents and list open action items.`,
      "What risks or issues are currently identified? Cite document sources.",
      "Which entities or locations have the most outstanding items?",
      "What deadlines or expiration dates require attention in the next 90 days?",
      "Are there any regulatory or contractual requirements needing immediate action?",
    ];
  })();

  async function sendMessage(question: string) {
    if (!question.trim() || loading) return;
    const userMsg: Message = { role: "user", content: question, timestamp: nowStamp() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const base = getApiBaseUrl();
      const resp = await fetch(`${base}/api/docintel/agent-query?${domainParam}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          incident_ref: activeIncidentId || undefined,
          chat_history: messages
            .filter((m, idx) => !(m.role === "assistant" && idx === 0))
            .map(m => ({ role: m.role, content: m.content })),
        }),
      });
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      const data = await resp.json();
      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.answer || "I couldn't generate an answer. Please try rephrasing.",
        timestamp: nowStamp(),
        tools_used: data.tools_used,
        fallback: data.fallback,
      }]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Error: ${msg}. Please ensure the backend is running and the agent is deployed.`,
        timestamp: nowStamp(),
      }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col">

      {/* ── Incident selector bar (supply chain only) ── */}
      {isSupplyChain && (
        <div className={`border-b px-6 py-3 ${
          activeIncident?.severity === "critical" ? "bg-red-50 border-red-200" :
          activeIncident?.severity === "high"     ? "bg-orange-50 border-orange-200" :
          "bg-white border-gray-200"
        }`}>
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest flex-shrink-0">Active Incident</span>
            <div className="relative flex-shrink-0">
              <select
                value={activeIncidentId}
                onChange={e => setActiveIncidentId(e.target.value)}
                className="appearance-none pl-3 pr-8 py-1.5 rounded-lg border border-gray-300 bg-white text-sm font-semibold text-gray-800 shadow-sm cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-400 hover:border-blue-400 transition-colors"
              >
                {incidents.length === 0
                  ? <option value={activeIncidentId}>{activeIncidentId || "Loading…"}</option>
                  : incidents.map(inc => (
                      <option key={inc.incident_id} value={inc.incident_id}>
                        {inc.incident_id} — {inc.title}
                      </option>
                    ))
                }
              </select>
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs">▼</span>
            </div>
            {activeIncident && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${SEV_COLOR[activeIncident.severity] ?? ""}`}>
                  {STATUS_ICON[activeIncident.status] ?? "📋"} {activeIncident.severity.toUpperCase()}
                </span>
                <span className="text-xs text-gray-600">{activeIncident.primary_entity_label}</span>
                <span className="text-[10px] text-gray-400">·</span>
                <span className="text-xs font-mono text-gray-600">${(activeIncident.financial_exposure_usd / 1000).toFixed(0)}K exposure</span>
                <span className="text-[10px] text-gray-400">·</span>
                <span className="text-xs text-gray-400">{activeIncident.affected_count} {activeIncident.affected_label}</span>
              </div>
            )}
            <span className="ml-auto text-[10px] text-gray-400 hidden sm:block">{domainName} · {domainId}</span>
          </div>
          <p className="text-[10px] text-gray-400 mt-1">
            {incidents.length} incident{incidents.length !== 1 ? "s" : ""} available · Agent answers are scoped to the selected incident
          </p>
        </div>
      )}

      {/* ── Compliance domain header bar ── */}
      {!isSupplyChain && (
        <div className="border-b px-6 py-3 bg-indigo-50 border-indigo-200">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[10px] font-bold text-indigo-500 uppercase tracking-widest">{domainName} Copilot</span>
            <span className="text-xs text-indigo-700 font-semibold">{domainName}</span>
            {savedPromptSnippet ? (
              <span className="text-[10px] text-indigo-400 truncate max-w-sm hidden sm:block">
                Guiding prompt active · {savedPromptSnippet.trim().slice(0, 80)}…
              </span>
            ) : (
              <span className="text-[10px] text-amber-500">No guiding prompt — set one in Copilot Studio</span>
            )}
            <a
              href="/supply-chain"
              className="ml-auto text-[10px] font-semibold text-indigo-600 hover:underline"
            >
              → Open Copilot Studio to edit prompt
            </a>
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-72 flex-shrink-0 bg-white border-r border-gray-200 p-4 overflow-auto hidden lg:block">

          {/* Active incident details (supply chain) */}
          {isSupplyChain && activeIncident && (
            <div className="mb-5">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Active Incident Context</p>
              <div className={`rounded-md p-3 text-xs space-y-1 border ${SEV_COLOR[activeIncident.severity] ?? "bg-gray-50 border-gray-200"}`}>
                <p><strong>ID:</strong> {activeIncident.incident_id}</p>
                <p><strong>Type:</strong> {activeIncident.incident_type.replace(/_/g," ")}</p>
                <p><strong>Status:</strong> {activeIncident.status}</p>
                <p><strong>Entity:</strong> {activeIncident.primary_entity_label}</p>
                <p><strong>Affected:</strong> {activeIncident.affected_count} {activeIncident.affected_label}</p>
                <p><strong>Exposure:</strong> ${(activeIncident.financial_exposure_usd/1000).toFixed(0)}K</p>
                <p><strong>Opened:</strong> {activeIncident.opened_date}</p>
              </div>
            </div>
          )}

          {/* Guiding prompt card (all domains) */}
          <div className="mb-5">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Guiding Prompt</p>
            {savedPromptSnippet ? (
              <div className="bg-indigo-50 border border-indigo-200 rounded-md p-3 text-xs text-indigo-800 space-y-1">
                <p className="font-semibold text-indigo-700">Active</p>
                <p className="text-indigo-600 leading-relaxed line-clamp-4">{savedPromptSnippet}…</p>
                <a href="/supply-chain" className="text-[10px] text-indigo-500 hover:underline">Edit in Copilot Studio →</a>
              </div>
            ) : (
              <div className="bg-amber-50 border border-amber-200 rounded-md p-3 text-xs text-amber-700 space-y-1">
                <p className="font-semibold">No prompt saved</p>
                <a href="/supply-chain" className="text-[10px] text-amber-600 hover:underline">Set up in Copilot Studio →</a>
              </div>
            )}
          </div>

          {/* Agent tools */}
          <div className="mb-5">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Agent Tools</p>
            <ul className="space-y-1.5 text-xs text-gray-600">
              {(isSupplyChain ? [
                "get_impacted_restaurants()",
                "get_financial_exposure()",
                "get_supplier_temp_violations()",
                "get_contract_liability()",
                "traverse_ontology()",
                "search_documents()",
              ] : [
                "get_entity_documents()",
                "get_extracted_fields_for_doc()",
                "search_by_field()",
                "get_entities_by_type()",
                "traverse_ontology()",
                "search_documents()",
              ]).map(t => (
                <li key={t} className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 bg-purple-400 rounded-full flex-shrink-0" />
                  <code className="font-mono">{t}</code>
                </li>
              ))}
            </ul>
          </div>

          {/* Suggested questions */}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Suggested Questions</p>
            <div className="space-y-1.5">
              {SUGGESTED.map((q, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(q)}
                  disabled={loading}
                  className="w-full text-left text-xs text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-100 rounded-md p-2 leading-snug transition-colors disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* Chat area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-auto p-6 space-y-4">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-2xl rounded-lg px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-white border border-gray-200 text-gray-800"
                }`}>
                  {/* Use structured sections renderer when LLM returns structured output */}
                  {msg.role === "assistant" && hasCopilotSections(msg.content)
                    ? <AgentStructuredResponse content={msg.content} />
                    : <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
                  }
                  <div className={`mt-1.5 flex gap-3 text-xs ${msg.role === "user" ? "text-blue-200 justify-end" : "text-gray-400"}`}>
                    <span>{msg.timestamp}</span>
                    {msg.tools_used != null && <span>{msg.tools_used} tools</span>}
                    {isSupplyChain && activeIncidentId && msg.role === "assistant" && i > 0 && (
                      <span className="text-gray-300">Incident: {activeIncidentId}</span>
                    )}
                    {msg.fallback && <span className="text-amber-500">SQL fallback</span>}
                  </div>
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-500 flex items-center gap-2">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                  Thinking — consulting {domainName.toLowerCase()} knowledge base…
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="flex-shrink-0 bg-white border-t border-gray-200 p-4">
            <form onSubmit={e => { e.preventDefault(); sendMessage(input); }} className="flex gap-3">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={isSupplyChain
                  ? (activeIncidentId
                      ? `Ask about ${activeIncidentId} — documents, exposure, liability, corrective actions…`
                      : `Ask about ${domainName.toLowerCase()} documents, suppliers, risks…`)
                  : "Ask a compliance or regulatory question — grounded in your parsed documents…"
                }
                className="flex-1 text-sm border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={loading}
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? "…" : "Ask"}
              </button>
            </form>
            <p className="text-xs text-gray-400 mt-2 text-center">
              {isSupplyChain
                ? <><code>jai_docintel.agents.*</code> UC Functions · DBRX Instruct · Vector Search{activeIncidentId && <span> · Scoped to {activeIncidentId}</span>}</>
                : <><code>jai_docintel.{domainId}.*</code> · DBRX Instruct · Vector Search · Guided by saved prompt</>
              }
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
