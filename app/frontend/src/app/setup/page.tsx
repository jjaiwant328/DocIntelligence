"use client";

/**
 * 7-step Domain Setup Wizard
 *
 * Step 1 — Identity       (name + description)
 * Step 2 — Doc Types      (classification labels — AI-assisted)
 * Step 3 — Extraction     (field schemas per doc type — AI-assisted)
 * Step 4 — Ontology       (entity types + key relationships)
 * Step 5 — Analytics      (key panels + field mappings)
 * Step 6 — Initialize     (provision UC schema + volume)
 * Step 7 — Activate       (test pipeline + confirm go-live)
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WizardState {
  // Step 1
  domain_id: string;
  name: string;
  description: string;
  // Step 2
  classificationLabels: Record<string, string>;
  // Step 3
  extractionSchemas: Record<string, Record<string, { type: string; description: string }>>;
  // Step 4
  entityTypes: string[];
  // Step 5
  analytics_config: Record<string, string>;
  suggested_questions: string[];
  // Step 6
  agent_system_prompt: string;
}

const INITIAL_STATE: WizardState = {
  domain_id: "",
  name: "",
  description: "",
  classificationLabels: {},
  extractionSchemas: {},
  entityTypes: [],
  analytics_config: {},
  suggested_questions: [],
  agent_system_prompt: "",
};

const STEP_TITLES = [
  "Domain Identity",
  "Document Types",
  "Extraction Schema",
  "Ontology Config",
  "Analytics Setup",
  "Initialize",
  "Activate",
];

const STEP_DESCRIPTIONS = [
  "Name your subject area and describe what it covers",
  "Define the types of documents this domain will process",
  "Map extraction fields to each document type",
  "Define the entity types and key relationships",
  "Configure analytics panels and key field mappings",
  "Provision the Unity Catalog schema and storage volume",
  "Run a test pipeline and go live",
];

// ── Utils ──────────────────────────────────────────────────────────────────────

// Live: allow trailing underscore while typing so the user can type "audit_report" directly
function toSnakeCaseLive(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9_]+/g, "_");
}
// Final: strip leading/trailing underscores on save
function toSnakeCaseFinal(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

// ── Wizard Component ──────────────────────────────────────────────────────────

export default function SetupWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [initRunId, setInitRunId] = useState<number | null>(null);
  const [activateSuccess, setActivateSuccess] = useState(false);

  // AI suggestion state
  const [suggestingLabels, setSuggestingLabels] = useState(false);
  const [suggestingSchema, setSuggestingSchema] = useState<string>("");
  const [newLabelKey, setNewLabelKey] = useState("");
  const [newLabelDesc, setNewLabelDesc] = useState("");
  const [newEntityType, setNewEntityType] = useState("");
  const [selectedDocType, setSelectedDocType] = useState("");
  const [newFieldKey, setNewFieldKey] = useState("");
  const [newFieldDesc, setNewFieldDesc] = useState("");

  // ── Helpers ──────────────────────────────────────────────────────────────────

  const update = (patch: Partial<WizardState>) => setState(s => ({ ...s, ...patch }));

  const apiPost = async (url: string, body: object) => {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };

  const apiPut = async (url: string, body: object) => {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };

  const goNext = () => setStep(s => Math.min(s + 1, 7));
  const goBack = () => setStep(s => Math.max(s - 1, 1));

  // ── Step actions ──────────────────────────────────────────────────────────────

  const handleSuggestLabels = async () => {
    setSuggestingLabels(true);
    setError("");
    try {
      const data = await apiPost("/api/platform/setup/suggest-labels", {
        domain_name: state.name,
        domain_description: state.description,
      });
      if (data.labels && Object.keys(data.labels).length > 0) {
        update({ classificationLabels: { ...state.classificationLabels, ...data.labels } });
      } else {
        setError("AI couldn't suggest labels — you can add them manually below.");
      }
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setSuggestingLabels(false);
    }
  };

  const handleSuggestSchema = async (docTypeKey: string) => {
    setSuggestingSchema(docTypeKey);
    setError("");
    try {
      const data = await apiPost("/api/platform/setup/suggest-schema", {
        domain_name: state.name,
        doc_type_label: docTypeKey,
        doc_type_description: state.classificationLabels[docTypeKey] ?? "",
      });
      if (data.schema && Object.keys(data.schema).length > 0) {
        update({
          extractionSchemas: {
            ...state.extractionSchemas,
            [docTypeKey]: { ...(state.extractionSchemas[docTypeKey] ?? {}), ...data.schema },
          },
        });
      }
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setSuggestingSchema("");
    }
  };

  const saveStep1And2 = async () => {
    if (!state.name.trim()) { setError("Domain name is required."); return; }
    setLoading(true); setError("");
    try {
      const domain_id = toSnakeCaseFinal(state.name);
      update({ domain_id });
      // Check if domain already exists; create or update
      const existing = await fetch(`/api/platform/domains/${domain_id}`);
      if (existing.status === 404) {
        await apiPost("/api/platform/domains", {
          domain_id,
          name: state.name,
          description: state.description,
        });
      }
      // Save labels
      await apiPut(`/api/platform/domains/${domain_id}`, {
        name: state.name,
        description: state.description,
        classification_labels: JSON.stringify(state.classificationLabels),
      });
      goNext();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const saveStep3 = async () => {
    setLoading(true); setError("");
    try {
      await apiPut(`/api/platform/domains/${state.domain_id}`, {
        extraction_schemas: JSON.stringify(state.extractionSchemas),
      });
      goNext();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const saveStep4 = async () => {
    setLoading(true); setError("");
    try {
      await apiPut(`/api/platform/domains/${state.domain_id}`, {
        entity_types: JSON.stringify(state.entityTypes),
        agent_system_prompt: state.agent_system_prompt,
      });
      goNext();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const saveStep5 = async () => {
    setLoading(true); setError("");
    try {
      await apiPut(`/api/platform/domains/${state.domain_id}`, {
        analytics_config: JSON.stringify(state.analytics_config),
        suggested_questions: JSON.stringify(state.suggested_questions),
      });
      goNext();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleInitialize = async () => {
    setLoading(true); setError("");
    try {
      const data = await apiPost("/api/platform/setup/initialize", { domain_id: state.domain_id });
      if (data.run_id) setInitRunId(data.run_id);
      goNext();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleActivate = async () => {
    setLoading(true); setError("");
    try {
      await apiPost("/api/platform/setup/activate", { domain_id: state.domain_id });
      setActivateSuccess(true);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <button
          onClick={() => router.push("/")}
          className="text-xs text-gray-400 hover:text-gray-700 flex items-center gap-1"
        >
          ← Domains
        </button>
        <span className="text-gray-200">|</span>
        <h1 className="text-sm font-bold text-gray-900">New Subject Area Setup</h1>
      </div>

      {/* Step progress */}
      <div className="bg-white border-b border-gray-100 px-6 py-3">
        <div className="max-w-3xl mx-auto flex items-center gap-0">
          {STEP_TITLES.map((title, i) => {
            const n = i + 1;
            const done = step > n;
            const active = step === n;
            return (
              <div key={n} className="flex items-center flex-1 last:flex-none">
                <div className="flex flex-col items-center">
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
                    ${done ? "bg-green-500 text-white" : active ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-400"}`}>
                    {done ? "✓" : n}
                  </div>
                  <span className={`mt-1 text-[9px] font-medium text-center max-w-[56px] leading-tight
                    ${active ? "text-blue-700" : done ? "text-green-600" : "text-gray-400"}`}>
                    {title}
                  </span>
                </div>
                {i < STEP_TITLES.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-1 mb-5 transition-colors ${step > n ? "bg-green-300" : "bg-gray-200"}`} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Step content */}
      <div className="flex-1 max-w-3xl mx-auto w-full px-6 py-8">
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-bold text-gray-900 mb-1">Step {step}: {STEP_TITLES[step - 1]}</h2>
          <p className="text-xs text-gray-500 mb-6">{STEP_DESCRIPTIONS[step - 1]}</p>

          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-xs text-red-700">
              {error}
            </div>
          )}

          {/* ── Step 1: Identity ── */}
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Domain Name *</label>
                <input
                  type="text"
                  value={state.name}
                  onChange={e => update({ name: e.target.value, domain_id: toSnakeCaseFinal(e.target.value) })}
                  placeholder="e.g. Compliance, Procurement, Finance"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {state.domain_id && (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Domain ID: <code className="bg-gray-100 px-1 rounded">{state.domain_id}</code>
                  </p>
                )}
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Description</label>
                <textarea
                  rows={4}
                  value={state.description}
                  onChange={e => update({ description: e.target.value })}
                  placeholder="Describe what this domain covers and what types of documents are typical (e.g. Compliance documents include audit reports, policy reviews, regulatory filings, and risk assessments)."
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  A detailed description helps AI suggest better document types and extraction schemas.
                </p>
              </div>
              <button
                onClick={() => {
                  if (!state.name.trim()) { setError("Domain name is required."); return; }
                  setError("");
                  goNext();
                }}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors"
              >
                Continue →
              </button>
            </div>
          )}

          {/* ── Step 2: Document Types ── */}
          {step === 2 && (
            <div className="space-y-5">
              <div className="flex gap-3">
                <button
                  onClick={handleSuggestLabels}
                  disabled={suggestingLabels}
                  className="flex items-center gap-2 px-4 py-2 bg-purple-50 hover:bg-purple-100 border border-purple-200 text-purple-700 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50"
                >
                  {suggestingLabels ? "Thinking…" : "✨ AI Suggest Labels"}
                </button>
                <p className="text-xs text-gray-400 flex-1 self-center">
                  Or add document types manually below
                </p>
              </div>

              {/* Current labels */}
              {Object.keys(state.classificationLabels).length > 0 && (
                <div className="space-y-2">
                  {Object.entries(state.classificationLabels).map(([key, desc]) => (
                    <div key={key} className="flex items-start gap-2 bg-gray-50 rounded-lg px-3 py-2">
                      <code className="text-[10px] font-bold text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded whitespace-nowrap mt-0.5">
                        {key}
                      </code>
                      <span className="text-xs text-gray-600 flex-1">{desc}</span>
                      <button
                        onClick={() => {
                          const updated = { ...state.classificationLabels };
                          delete updated[key];
                          update({ classificationLabels: updated });
                        }}
                        className="text-gray-300 hover:text-red-500 text-xs ml-1 flex-shrink-0"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Add manually */}
              <div className="border border-dashed border-gray-200 rounded-lg p-4 space-y-3">
                <p className="text-xs font-semibold text-gray-600">Add a document type</p>
                <div>
                  <input
                    type="text"
                    value={newLabelKey}
                    onChange={e => setNewLabelKey(toSnakeCaseLive(e.target.value))}
                    placeholder="label_key  (e.g. audit_report)"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <p className="text-[10px] text-gray-400 mt-1">Type with underscores or spaces — spaces are converted to underscores automatically.</p>
                </div>
                <div>
                  <input
                    type="text"
                    value={newLabelDesc}
                    onChange={e => setNewLabelDesc(e.target.value)}
                    placeholder="e.g. Supplier audit report listing findings, corrective actions, and compliance status"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <p className="text-[10px] text-gray-400 mt-1">
                    This description is passed to <code className="bg-gray-100 px-1 rounded">ai_classify()</code> as a label hint.
                    Be specific — describe the distinguishing content, not just the name.
                  </p>
                </div>
                <button
                  onClick={() => {
                    const key = toSnakeCaseFinal(newLabelKey);
                    if (!key || !newLabelDesc) return;
                    update({ classificationLabels: { ...state.classificationLabels, [key]: newLabelDesc } });
                    setNewLabelKey(""); setNewLabelDesc("");
                  }}
                  className="px-4 py-1.5 bg-gray-800 text-white text-xs font-semibold rounded-lg hover:bg-gray-700 transition-colors"
                >
                  + Add
                </button>
              </div>

              <div className="flex gap-3 pt-2">
                <button onClick={goBack} className="flex-1 border border-gray-200 hover:border-gray-300 text-gray-600 text-sm font-semibold py-2.5 rounded-lg transition-colors">
                  ← Back
                </button>
                <button
                  onClick={saveStep1And2}
                  disabled={loading || Object.keys(state.classificationLabels).length === 0}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {loading ? "Saving…" : "Save & Continue →"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 3: Extraction Schema ── */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-xs text-gray-500">
                For each document type, define the structured fields to extract.
                AI can suggest fields based on the document type description.
              </p>

              {/* Doc type picker */}
              <div className="flex gap-2 flex-wrap">
                {Object.keys(state.classificationLabels).map(key => (
                  <button
                    key={key}
                    onClick={() => setSelectedDocType(key)}
                    className={`px-3 py-1.5 text-xs rounded-full font-medium border transition-colors
                      ${selectedDocType === key
                        ? "bg-blue-600 text-white border-blue-600"
                        : "bg-white text-gray-600 border-gray-200 hover:border-blue-300"
                      }`}
                  >
                    {key}
                    {state.extractionSchemas[key] && (
                      <span className="ml-1 text-green-400">✓</span>
                    )}
                  </button>
                ))}
              </div>

              {selectedDocType && (
                <div className="border border-gray-200 rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold text-gray-800">{selectedDocType}</h4>
                    <button
                      onClick={() => handleSuggestSchema(selectedDocType)}
                      disabled={suggestingSchema === selectedDocType}
                      className="flex items-center gap-1 px-3 py-1 bg-purple-50 hover:bg-purple-100 border border-purple-200 text-purple-700 text-[10px] font-semibold rounded-lg transition-colors disabled:opacity-50"
                    >
                      {suggestingSchema === selectedDocType ? "Thinking…" : "✨ AI Suggest Fields"}
                    </button>
                  </div>

                  {/* Existing fields */}
                  {Object.entries(state.extractionSchemas[selectedDocType] ?? {}).map(([field, meta]) => (
                    <div key={field} className="flex items-start gap-2 bg-gray-50 rounded px-2 py-1.5">
                      <code className="text-[10px] font-bold text-blue-700 whitespace-nowrap">{field}</code>
                      <span className="text-[10px] text-gray-500 flex-1">{meta.description}</span>
                      <button
                        onClick={() => {
                          const updated = { ...state.extractionSchemas };
                          if (updated[selectedDocType]) {
                            const fieldsUpdated = { ...updated[selectedDocType] };
                            delete fieldsUpdated[field];
                            updated[selectedDocType] = fieldsUpdated;
                          }
                          update({ extractionSchemas: updated });
                        }}
                        className="text-gray-300 hover:text-red-500 text-[10px]"
                      >✕</button>
                    </div>
                  ))}

                  {/* Add field manually */}
                  <div className="flex gap-2 pt-1">
                    <input
                      type="text"
                      value={newFieldKey}
                      onChange={e => setNewFieldKey(toSnakeCaseLive(e.target.value))}
                      placeholder="field_name"
                      className="flex-1 border border-gray-200 rounded px-2 py-1 text-[10px] focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                    <input
                      type="text"
                      value={newFieldDesc}
                      onChange={e => setNewFieldDesc(e.target.value)}
                      placeholder="Description for extraction"
                      className="flex-[2] border border-gray-200 rounded px-2 py-1 text-[10px] focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                    <button
                      onClick={() => {
                        if (!newFieldKey || !newFieldDesc || !selectedDocType) return;
                        update({
                          extractionSchemas: {
                            ...state.extractionSchemas,
                            [selectedDocType]: {
                              ...(state.extractionSchemas[selectedDocType] ?? {}),
                              [newFieldKey]: { type: "string", description: newFieldDesc },
                            },
                          },
                        });
                        setNewFieldKey(""); setNewFieldDesc("");
                      }}
                      className="px-3 py-1 bg-gray-800 text-white text-[10px] font-semibold rounded hover:bg-gray-700"
                    >+ Add</button>
                  </div>
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button onClick={goBack} className="flex-1 border border-gray-200 hover:border-gray-300 text-gray-600 text-sm font-semibold py-2.5 rounded-lg">
                  ← Back
                </button>
                <button
                  onClick={saveStep3}
                  disabled={loading}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg disabled:opacity-50"
                >
                  {loading ? "Saving…" : "Save & Continue →"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 4: Ontology Config ── */}
          {step === 4 && (
            <div className="space-y-5">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-2">Entity Types</label>
                <p className="text-[10px] text-gray-400 mb-3">
                  Define the types of entities the ontology pipeline will extract from documents
                  (e.g. Supplier, Contract, Policy, Audit, Employee).
                </p>
                <div className="flex flex-wrap gap-2 mb-3">
                  {state.entityTypes.map(et => (
                    <span key={et} className="inline-flex items-center gap-1.5 px-3 py-1 bg-blue-50 border border-blue-200 text-blue-700 text-xs rounded-full">
                      {et}
                      <button onClick={() => update({ entityTypes: state.entityTypes.filter(e => e !== et) })}
                        className="text-blue-300 hover:text-red-500 text-[10px]">✕</button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newEntityType}
                    onChange={e => setNewEntityType(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter" && newEntityType.trim()) {
                        update({ entityTypes: [...state.entityTypes, newEntityType.trim()] });
                        setNewEntityType("");
                      }
                    }}
                    placeholder="EntityType (press Enter to add)"
                    className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    onClick={() => {
                      if (!newEntityType.trim()) return;
                      update({ entityTypes: [...state.entityTypes, newEntityType.trim()] });
                      setNewEntityType("");
                    }}
                    className="px-4 py-2 bg-gray-800 text-white text-xs font-semibold rounded-lg hover:bg-gray-700"
                  >+ Add</button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Agent System Prompt</label>
                <textarea
                  rows={5}
                  value={state.agent_system_prompt}
                  onChange={e => update({ agent_system_prompt: e.target.value })}
                  placeholder={`You are the ${state.name} AI assistant. You answer questions about ${state.name.toLowerCase()} documents and data. Be precise and cite document sources.`}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                />
              </div>

              <div className="flex gap-3 pt-2">
                <button onClick={goBack} className="flex-1 border border-gray-200 text-gray-600 text-sm font-semibold py-2.5 rounded-lg">← Back</button>
                <button onClick={saveStep4} disabled={loading} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg disabled:opacity-50">
                  {loading ? "Saving…" : "Save & Continue →"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 5: Analytics Setup ── */}
          {step === 5 && (
            <div className="space-y-5">
              <p className="text-xs text-gray-500">
                Configure the Control Tower panels for this domain and add suggested questions
                for the AI chat interface.
              </p>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Primary Incident ID Field</label>
                <input
                  type="text"
                  value={state.analytics_config.incident_id_field ?? ""}
                  onChange={e => update({ analytics_config: { ...state.analytics_config, incident_id_field: e.target.value } })}
                  placeholder="e.g. recall_number, audit_id, po_number"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Example Incident Reference</label>
                <input
                  type="text"
                  value={state.analytics_config.incident_ref_example ?? ""}
                  onChange={e => update({ analytics_config: { ...state.analytics_config, incident_ref_example: e.target.value } })}
                  placeholder="e.g. AUD-2024-001, PO-2024-0042"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-2">Suggested Questions for AI Agent</label>
                <div className="space-y-1.5 mb-3">
                  {state.suggested_questions.map((q, i) => (
                    <div key={i} className="flex items-center gap-2 bg-gray-50 rounded px-3 py-1.5">
                      <span className="text-xs text-gray-600 flex-1">{q}</span>
                      <button onClick={() => update({ suggested_questions: state.suggested_questions.filter((_, j) => j !== i) })}
                        className="text-gray-300 hover:text-red-500 text-xs">✕</button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    id="sq-input"
                    type="text"
                    placeholder="Add a suggested question…"
                    className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    onKeyDown={e => {
                      if (e.key === "Enter") {
                        const val = (e.target as HTMLInputElement).value.trim();
                        if (val) {
                          update({ suggested_questions: [...state.suggested_questions, val] });
                          (e.target as HTMLInputElement).value = "";
                        }
                      }
                    }}
                  />
                  <button
                    onClick={() => {
                      const el = document.getElementById("sq-input") as HTMLInputElement;
                      if (el?.value.trim()) {
                        update({ suggested_questions: [...state.suggested_questions, el.value.trim()] });
                        el.value = "";
                      }
                    }}
                    className="px-4 py-2 bg-gray-800 text-white text-xs font-semibold rounded-lg hover:bg-gray-700"
                  >+ Add</button>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button onClick={goBack} className="flex-1 border border-gray-200 text-gray-600 text-sm font-semibold py-2.5 rounded-lg">← Back</button>
                <button onClick={saveStep5} disabled={loading} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg disabled:opacity-50">
                  {loading ? "Saving…" : "Save & Continue →"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 6: Initialize ── */}
          {step === 6 && (
            <div className="space-y-5">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h3 className="text-xs font-bold text-blue-800 mb-2">What will be provisioned</h3>
                <ul className="text-xs text-blue-700 space-y-1">
                  <li>• Unity Catalog schema: <code className="bg-blue-100 px-1 rounded">jai_docintel.{state.domain_id}</code></li>
                  <li>• Document volume: <code className="bg-blue-100 px-1 rounded">/Volumes/jai_docintel/{state.domain_id}/documents/</code></li>
                  <li>• Delta tables: parsed_documents, extracted_fields, entities, relationships</li>
                  <li>• Vector Search index and AI agent UC Functions</li>
                </ul>
              </div>

              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                <h3 className="text-xs font-bold text-gray-700 mb-3">Configuration Summary</h3>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                  <div><dt className="text-gray-400">Domain ID</dt><dd className="font-mono font-semibold text-gray-800">{state.domain_id}</dd></div>
                  <div><dt className="text-gray-400">Name</dt><dd className="font-semibold text-gray-800">{state.name}</dd></div>
                  <div><dt className="text-gray-400">Document Types</dt><dd className="font-semibold text-gray-800">{Object.keys(state.classificationLabels).length}</dd></div>
                  <div><dt className="text-gray-400">Entity Types</dt><dd className="font-semibold text-gray-800">{state.entityTypes.length}</dd></div>
                  <div><dt className="text-gray-400">Extraction Schemas</dt><dd className="font-semibold text-gray-800">{Object.keys(state.extractionSchemas).length}</dd></div>
                  <div><dt className="text-gray-400">Suggested Questions</dt><dd className="font-semibold text-gray-800">{state.suggested_questions.length}</dd></div>
                </dl>
              </div>

              {initRunId && (
                <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-xs text-green-700">
                  ✓ Setup job triggered (Run ID: {initRunId}). The schema and pipeline are being provisioned.
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button onClick={goBack} className="flex-1 border border-gray-200 text-gray-600 text-sm font-semibold py-2.5 rounded-lg">← Back</button>
                <button
                  onClick={handleInitialize}
                  disabled={loading}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2.5 rounded-lg disabled:opacity-50"
                >
                  {loading ? "Provisioning…" : "🚀 Initialize Domain"}
                </button>
              </div>
            </div>
          )}

          {/* ── Step 7: Activate ── */}
          {step === 7 && (
            <div className="space-y-5">
              {!activateSuccess ? (
                <>
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-xs text-amber-800">
                    <strong>Before activating:</strong> Make sure the setup pipeline run has completed successfully.
                    {initRunId && (
                      <div className="mt-2">Run ID: <code className="bg-amber-100 px-1 rounded">{initRunId}</code></div>
                    )}
                    Check your Databricks workspace for the job status.
                  </div>

                  <div className="bg-gray-50 rounded-lg p-4 text-xs text-gray-600 space-y-2">
                    <p className="font-semibold">Once active, you can:</p>
                    <ul className="space-y-1 ml-3">
                      <li>• Upload documents via the Document Intelligence panel</li>
                      <li>• Run the full AI pipeline (classify, extract, ontology, vectors)</li>
                      <li>• Query via the AI Agent with your custom domain prompt</li>
                      <li>• Monitor incidents in the Control Tower</li>
                    </ul>
                  </div>

                  <div className="flex gap-3 pt-2">
                    <button onClick={goBack} className="flex-1 border border-gray-200 text-gray-600 text-sm font-semibold py-2.5 rounded-lg">← Back</button>
                    <button
                      onClick={handleActivate}
                      disabled={loading}
                      className="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold py-2.5 rounded-lg disabled:opacity-50"
                    >
                      {loading ? "Activating…" : "✅ Activate Domain"}
                    </button>
                  </div>
                </>
              ) : (
                <div className="text-center py-8">
                  <div className="text-5xl mb-4">🎉</div>
                  <h3 className="text-xl font-bold text-gray-900 mb-2">
                    {state.name} is Live!
                  </h3>
                  <p className="text-sm text-gray-500 mb-6">
                    Your new domain is configured and ready to process documents.
                  </p>
                  <button
                    onClick={() => router.push("/")}
                    className="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors"
                  >
                    Go to Domain Selector →
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
