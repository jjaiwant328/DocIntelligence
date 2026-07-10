"use client";

import { useState, useEffect } from "react";
import { getApiBaseUrl } from "@/lib/api-config";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DocDetail {
    doc_id: string;
    filename: string;
    doc_type: string;
    doc_type_label?: string;
    processed_ts?: string;
    char_count?: number;
    est_word_count?: number;
    entity_count?: number;
    text_preview?: string;
    raw_text?: string;
    extracted_fields?: Record<string, string>;
    related_entities?: { display_name: string; entity_type: string }[];
}

const DOC_TYPE_COLORS: Record<string, string> = {
    inspection_report:      "bg-blue-100 text-blue-800 border-blue-200",
    policy_document:        "bg-purple-100 text-purple-800 border-purple-200",
    audit_report:           "bg-amber-100 text-amber-800 border-amber-200",
    corrective_action_plan: "bg-orange-100 text-orange-800 border-orange-200",
    vendor_certification:   "bg-green-100 text-green-800 border-green-200",
    email_thread:           "bg-pink-100 text-pink-800 border-pink-200",
    permit:                 "bg-teal-100 text-teal-800 border-teal-200",
    training_certificate:   "bg-indigo-100 text-indigo-800 border-indigo-200",
    license:                "bg-cyan-100 text-cyan-800 border-cyan-200",
    incident_report:        "bg-red-100 text-red-800 border-red-200",
    risk_assessment:        "bg-rose-100 text-rose-800 border-rose-200",
    regulatory_change:      "bg-yellow-100 text-yellow-800 border-yellow-200",
};

function fmtTs(ts?: string) {
    if (!ts) return "";
    try { return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
    catch { return ts; }
}

// ── DocViewerPanel ─────────────────────────────────────────────────────────────

interface DocViewerPanelProps {
    docId: string;
    domainId: string;
    /** Initial data (from search snippet) — panel will load full detail on open */
    initialData?: { filename?: string; doc_type?: string; snippet?: string };
    onClose: () => void;
}

export function DocViewerPanel({ docId, domainId, initialData, onClose }: DocViewerPanelProps) {
    const [doc, setDoc]               = useState<DocDetail | null>(null);
    const [loading, setLoading]       = useState(true);
    const [expandedText, setExpanded] = useState(false);

    const apiBase = getApiBaseUrl();

    useEffect(() => {
        setLoading(true);
        setDoc(null);
        setExpanded(false);
        fetch(`${apiBase}/api/docintel/document-detail?doc_id=${encodeURIComponent(docId)}&domain_id=${encodeURIComponent(domainId)}`)
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) setDoc(d); })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, [docId, domainId, apiBase]);

    // Close on Escape
    useEffect(() => {
        const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
        document.addEventListener("keydown", handler);
        return () => document.removeEventListener("keydown", handler);
    }, [onClose]);

    const d = doc ?? (initialData ? { doc_id: docId, filename: initialData.filename ?? docId, doc_type: initialData.doc_type ?? "", raw_text: initialData.snippet } as DocDetail : null);
    const colorCls = d ? (DOC_TYPE_COLORS[d.doc_type] ?? "bg-gray-100 text-gray-800 border-gray-200") : "";
    const fullText = d?.raw_text ?? d?.text_preview ?? "";

    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-black/30 z-40 transition-opacity"
                onClick={onClose}
            />
            {/* Slide-over panel */}
            <div className="fixed top-0 right-0 h-full w-full max-w-2xl bg-white shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-200">
                {/* Header */}
                <div className="flex items-start gap-3 px-5 py-4 border-b border-gray-200 flex-shrink-0">
                    <div className="flex-1 min-w-0">
                        {d && (
                            <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full border mb-1.5 ${colorCls}`}>
                                {d.doc_type_label ?? d.doc_type}
                            </span>
                        )}
                        <h2 className="text-sm font-bold text-gray-900 leading-snug truncate">
                            {loading && !d ? "Loading…" : (d?.filename ?? docId)}
                        </h2>
                        {d && (
                            <div className="flex gap-3 text-[10px] text-gray-400 mt-1 flex-wrap">
                                {d.processed_ts && <span>Processed {fmtTs(d.processed_ts)}</span>}
                                {d.est_word_count && <span>~{Number(d.est_word_count).toLocaleString()} words</span>}
                                {(d.entity_count ?? 0) > 0 && <span>{d.entity_count} entities</span>}
                            </div>
                        )}
                    </div>
                    <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors flex-shrink-0">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
                    {loading && !doc && (
                        <div className="space-y-3 animate-pulse">
                            <div className="h-3 bg-gray-200 rounded w-3/4" />
                            <div className="h-3 bg-gray-200 rounded w-1/2" />
                            <div className="h-3 bg-gray-200 rounded w-2/3" />
                        </div>
                    )}

                    {/* Extracted Fields */}
                    {d && Object.keys(d.extracted_fields ?? {}).length > 0 && (
                        <section>
                            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">AI-Extracted Fields</h3>
                            <div className="space-y-1.5">
                                {Object.entries(d.extracted_fields!).map(([k, v]) => (
                                    <div key={k} className="flex gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-100">
                                        <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wide w-32 shrink-0 pt-0.5">{k.replace(/_/g, " ")}</span>
                                        <span className="text-xs text-gray-800 break-words">{String(v)}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    {/* Related Entities */}
                    {d && (d.related_entities ?? []).length > 0 && (
                        <section>
                            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Related Entities</h3>
                            <div className="flex flex-wrap gap-1.5">
                                {d.related_entities!.map((e, i) => (
                                    <div key={i} className="bg-white border border-gray-200 rounded-md px-2 py-1 text-xs flex items-center gap-1">
                                        <span className="font-medium text-gray-800">{e.display_name}</span>
                                        <span className="text-gray-400">· {e.entity_type}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    {/* Parsed Text */}
                    {d && fullText && (
                        <section>
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Document Text</h3>
                                {fullText.length > 600 && (
                                    <button onClick={() => setExpanded(v => !v)} className="text-xs text-blue-600 hover:text-blue-800">
                                        {expandedText ? "Show less" : "Show full text"}
                                    </button>
                                )}
                            </div>
                            <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 max-h-96 overflow-y-auto">
                                <pre className="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed font-mono">
                                    {expandedText ? fullText : (fullText.slice(0, 800) + (fullText.length > 800 ? "\n\n[… click Show full text to expand]" : ""))}
                                </pre>
                            </div>
                        </section>
                    )}

                    {!loading && !d && (
                        <p className="text-sm text-gray-400 italic">Could not load document detail.</p>
                    )}
                </div>
            </div>
        </>
    );
}
