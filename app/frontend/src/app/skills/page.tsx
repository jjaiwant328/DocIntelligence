"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";
import { FormattedOutputs } from "@/components/FormattedOutputs";

interface ManualInput { name: string; label: string; kind: string; placeholder?: string; required: boolean }
interface SkillMode {
  runnable_on_docs: boolean; runnable: boolean; needs_docs: boolean;
  manual_inputs: ManualInput[]; blocked_reason: string;
}
interface SkillMeta {
  id: string; category: string; enabled: boolean;
  description?: string; adapter?: string;
  inputs?: Record<string, { type?: string; required?: boolean }>;
  outputs?: Record<string, unknown>;
  side_effects?: Record<string, unknown>;
  mode?: SkillMode;
}
interface ParsedDoc { doc_id: string; doc_type?: string; doc_types?: string[] }
interface Evidence { document_id: string; source_text?: string; method?: string; }
interface SkillResult {
  status: string; outputs: Record<string, unknown>; evidence: Evidence[];
  error?: string | null; doc_id?: string;
  per_doc?: SkillResult[];   // one result per document when many are selected
}

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];

// A doc's categories, tolerant of doc_types arriving as an array, a JSON string
// (SQL collect_set serialized by run_sql), or a comma-joined doc_type string.
function docCategories(d: ParsedDoc): string[] {
  const dt = d.doc_types as unknown;
  if (Array.isArray(dt)) return dt.map(String);
  if (typeof dt === "string" && dt.trim()) {
    try {
      const parsed = JSON.parse(dt);
      if (Array.isArray(parsed)) return parsed.map(String);
    } catch { /* fall through to comma split */ }
    return dt.split(",").map((x) => x.trim()).filter(Boolean);
  }
  return d.doc_type ? String(d.doc_type).split(",").map((x) => x.trim()).filter(Boolean) : [];
}
function statusColor(s: string): string {
  if (["ok", "satisfied", "completed"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "error") return "bg-red-100 text-red-800";
  if (s === "gap") return "bg-orange-100 text-orange-800";
  if (s === "insufficient_evidence") return "bg-gray-200 text-gray-700";
  return "bg-blue-100 text-blue-800";
}

export default function SkillsTab({ domain }: { domain?: DomainInfo }) {
  const { project } = useDomain();
  const domainId = domain?.domain_id ?? "compliance_due_diligence";
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [docs, setDocs] = useState<ParsedDoc[]>([]);
  const [selected, setSelected] = useState<SkillMeta | null>(null);
  const [mode, setMode] = useState<"docs" | "manual">("docs");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [inputsText, setInputsText] = useState("{}");
  const [result, setResult] = useState<SkillResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // values the user types for manual inputs (query / question / labels …)
  const [manualValues, setManualValues] = useState<Record<string, string>>({});

  useEffect(() => {
    apiCall<{ skills: SkillMeta[] }>("/api/docintel/skills")
      .then((r) => setSkills(r.skills)).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    const q = `/api/docintel/parsed-documents?domain_id=${domainId}` +
      (project?.project_id ? `&project_id=${encodeURIComponent(project.project_id)}` : "");
    apiCall<{ documents: ParsedDoc[] }>(q)
      .then((r) => {
        setDocs(r.documents || []);
        // default: all selected
        const all: Record<string, boolean> = {};
        (r.documents || []).forEach((d) => { all[d.doc_id] = true; });
        setChecked(all);
      })
      .catch(() => setDocs([]));
  }, [domainId, project?.project_id]);

  function pick(s: SkillMeta) {
    setSelected(s); setResult(null); setError(null);
    setManualValues({});
    // default the mode to whatever the skill actually supports on documents
    setMode(s.mode?.needs_docs ? "docs" : "manual");
    const scaffold: Record<string, unknown> = {};
    Object.entries(s.inputs ?? {}).forEach(([k, spec]) => {
      if (spec.required) scaffold[k] = spec.type === "array" ? [] : "";
    });
    setInputsText(JSON.stringify(scaffold, null, 2));
  }

  const selectedDocIds = docs.filter((d) => checked[d.doc_id]).map((d) => d.doc_id);

  // Build the manual inputs object from typed values (splitting list kinds).
  function buildManualInputs(m: SkillMode): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    m.manual_inputs.forEach((mi) => {
      const raw = (manualValues[mi.name] ?? "").trim();
      if (!raw) return;
      out[mi.name] = mi.kind === "list"
        ? raw.split(",").map((x) => x.trim()).filter(Boolean)
        : raw;
    });
    return out;
  }

  // Which required manual inputs are still empty (block the run until filled).
  const missingManual: string[] = selected?.mode
    ? selected.mode.manual_inputs
        .filter((mi) => mi.required && !(manualValues[mi.name] ?? "").trim())
        .map((mi) => mi.label)
    : [];

  async function run() {
    if (!selected) return;
    setLoading(true); setError(null);
    try {
      const body: Record<string, unknown> = { skill: selected.id, domain_id: domainId };
      const manual = selected.mode ? buildManualInputs(selected.mode) : {};
      if (mode === "docs") {
        body.doc_ids = selectedDocIds;
        if (Object.keys(manual).length) body.inputs = manual;  // e.g. optional query
      } else if (selected.mode && selected.mode.manual_inputs.length) {
        body.inputs = manual;                                   // structured manual form
      } else {
        body.inputs = JSON.parse(inputsText || "{}");           // raw JSON fallback
      }
      const r = await apiCall<SkillResult>("/api/docintel/skill-invoke", {
        method: "POST", body: JSON.stringify(body),
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  const byCat = CATEGORY_ORDER
    .map((cat) => ({ cat, items: skills.filter((s) => s.category === cat) }))
    .filter((g) => g.items.length);

  return (
    <div className="px-4 py-4">
      <p className="text-sm text-gray-500 mb-3">
        Apply a skill to <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>&apos;s
        parsed documents{project?.project_id
          ? <> for project <span className="font-semibold text-gray-700">📁 {project.name || project.project_id}</span></>
          : <> (<span className="italic">all documents</span> — pick a project above to scope)</>}.
        Inputs are populated automatically from the documents you select.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* palette */}
        <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[70vh] overflow-y-auto">
          {error && <div className="mb-2 text-xs text-red-600">{error}</div>}
          {byCat.map((g) => (
            <div key={g.cat} className="mb-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{g.cat}</p>
              {g.items.map((s) => {
                const blocked = s.mode ? !s.mode.runnable : false;
                const needsInput = s.mode ? s.mode.manual_inputs.some((m) => m.required) : false;
                return (
                  <button key={s.id} onClick={() => pick(s)}
                    title={blocked ? s.mode?.blocked_reason : (needsInput ? "needs an input before running" : "runs on documents")}
                    className={`flex items-center gap-1.5 w-full text-left text-sm px-2 py-1 rounded ${
                      selected?.id === s.id ? "bg-blue-100 text-blue-800"
                      : blocked ? "text-gray-400 hover:bg-gray-50" : "hover:bg-gray-50"}`}>
                    <span className="truncate">{s.id}</span>
                    {s.side_effects?.creates_actions ? <span className="text-[10px] text-amber-600">✎</span> : null}
                    <span className="ml-auto flex-shrink-0">
                      {blocked
                        ? <span className="text-[9px] px-1 py-0.5 rounded bg-gray-100 text-gray-400">workflow</span>
                        : needsInput
                          ? <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 text-amber-700">input</span>
                          : <span className="text-[9px] px-1 py-0.5 rounded bg-green-100 text-green-700">docs</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* apply-to + run */}
        <div className="md:col-span-2">
          {!selected ? (
            <p className="text-sm text-gray-400">Select a skill to apply.</p>
          ) : (
            <div className="border border-gray-200 rounded-lg bg-white p-4">
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold text-gray-800">{selected.id}</h3>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{selected.adapter}</span>
              </div>
              <p className="text-sm text-gray-600 mt-1">{selected.description}</p>

              <SkillDetails skill={selected} />

              {/* Blocked: skill needs upstream workflow outputs — cannot run standalone */}
              {selected.mode && !selected.mode.runnable ? (
                <div className="mt-3 text-sm bg-gray-50 border border-gray-200 rounded p-3 text-gray-600">
                  <span className="font-medium text-gray-700">This skill runs inside a workflow.</span>{" "}
                  It {selected.mode.blocked_reason}. Build a workflow in the Workflows tab where an
                  earlier step produces those inputs.
                </div>
              ) : (
                <>
                  {/* mode toggle — only offer 'docs' when the skill can consume documents */}
                  {selected.mode?.needs_docs && (
                    <div className="mt-3 flex gap-4 text-sm">
                      <label className="flex items-center gap-1">
                        <input type="radio" checked={mode === "docs"} onChange={() => setMode("docs")} />
                        Parsed documents (auto)
                      </label>
                      <label className="flex items-center gap-1">
                        <input type="radio" checked={mode === "manual"} onChange={() => setMode("manual")} />
                        Manual input
                      </label>
                    </div>
                  )}

                  {/* Manual input form for query / question / labels etc. */}
                  {(mode === "manual" || !selected.mode?.needs_docs) && selected.mode && selected.mode.manual_inputs.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {selected.mode.manual_inputs.map((mi) => (
                        <label key={mi.name} className="block text-xs text-gray-600">
                          {mi.label}{mi.required && <span className="text-red-500"> *</span>}
                          <input
                            className="mt-1 w-full border rounded px-2 py-1.5 text-sm"
                            placeholder={mi.placeholder}
                            value={manualValues[mi.name] ?? ""}
                            onChange={(e) => setManualValues((v) => ({ ...v, [mi.name]: e.target.value }))}
                          />
                        </label>
                      ))}
                    </div>
                  )}

                  {/* Raw JSON fallback only when there's no structured manual form */}
                  {mode === "manual" && selected.mode && selected.mode.manual_inputs.length === 0 && (
                    <textarea className="mt-3 w-full h-32 border rounded p-2 font-mono text-xs"
                      value={inputsText} onChange={(e) => setInputsText(e.target.value)} />
                  )}

                  {/* Document picker */}
                  {mode === "docs" && selected.mode?.needs_docs && (
                    <>
                    {docs.length > 0 && (
                      <div className="mt-3 flex items-center gap-3 text-xs">
                        <span className="text-gray-500">{selectedDocIds.length} of {docs.length} selected</span>
                        <button onClick={() => setChecked(Object.fromEntries(docs.map((d) => [d.doc_id, true])))}
                          className="text-blue-600">Select all</button>
                        <button onClick={() => setChecked({})} className="text-gray-400">Clear all</button>
                      </div>
                    )}
                    <div className="mt-2 border rounded max-h-56 overflow-y-auto">
                      {docs.length === 0 ? (
                        <p className="text-xs text-gray-400 p-3">No parsed documents in this project yet.</p>
                      ) : docs.map((d) => {
                        const cats = docCategories(d);
                        return (
                          <label key={d.doc_id} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-gray-50 last:border-0">
                            <input type="checkbox" checked={!!checked[d.doc_id]}
                              onChange={(e) => setChecked((c) => ({ ...c, [d.doc_id]: e.target.checked }))} />
                            <span className="font-mono truncate">{d.doc_id}</span>
                            <span className="ml-auto flex flex-wrap gap-1 justify-end">
                              {cats.map((c) => (
                                <span key={c} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{c}</span>
                              ))}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                    </>
                  )}

                  {missingManual.length > 0 && (
                    <p className="mt-2 text-xs text-amber-700">Enter {missingManual.join(", ")} to run.</p>
                  )}

                  <button onClick={run}
                    disabled={loading
                      || (mode === "docs" && selected.mode?.needs_docs && !selectedDocIds.length)
                      || missingManual.length > 0}
                    className="mt-3 bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50">
                    {loading ? "Running…"
                      : mode === "docs" && selected.mode?.needs_docs ? `Run skill on ${selectedDocIds.length} document(s)`
                      : "Run skill"}
                  </button>
                </>
              )}

              {result && (
                <div className="mt-4">
                  {result.per_doc && result.per_doc.length > 0 ? (
                    <div>
                      <p className="text-xs text-gray-500 mb-2">
                        Ran on {result.per_doc.length} documents · {(result.outputs?.succeeded as number) ?? 0} succeeded.
                        One result per document:
                      </p>
                      <div className="space-y-3">
                        {result.per_doc.map((r, i) => (
                          <div key={i} className="border border-gray-100 rounded-lg p-2">
                            <p className="text-xs font-mono text-gray-700 mb-1">📄 {r.doc_id}</p>
                            <ResultBody r={r} />
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <ResultBody r={result} />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Human hints for how each input is sourced (used in the About panel).
const DOC_FED_INPUTS = new Set(["text", "context", "current", "previous", "conclusion"]);
const MANUAL_INPUT_NAMES = new Set(["query", "question", "labels", "entity_types", "doc_type"]);
function inputSource(name: string): string {
  if (DOC_FED_INPUTS.has(name)) return "from the selected document(s)";
  if (name === "schema_vec") return "auto (the project's vector schema)";
  if (name === "domain" || name === "project") return "auto (current project / project)";
  if (MANUAL_INPUT_NAMES.has(name)) return "you type it";
  return "produced by an earlier workflow step";
}

// Collapsible "About this skill" panel: inputs, outputs, dependencies, workflow usage.
function SkillDetails({ skill }: { skill: SkillMeta }) {
  const [open, setOpen] = useState(false);
  const inputs = Object.entries(skill.inputs ?? {});
  const outputs = Object.keys(skill.outputs ?? {});
  const mode = skill.mode;
  const usage = mode
    ? (mode.runnable_on_docs
        ? "Runs directly on documents. In a workflow, place it early to read the source documents."
        : mode.runnable
          ? "Needs a typed input (e.g. a search phrase). Can start a workflow or run standalone."
          : "Runs inside a workflow — an earlier step must produce its inputs.")
    : "";
  return (
    <div className="mt-2">
      <button onClick={() => setOpen((v) => !v)} className="text-xs text-blue-600">
        {open ? "▾ Hide details" : "▸ About this skill & how to use it"}
      </button>
      {open && (
        <div className="mt-2 text-xs text-gray-600 space-y-2 border border-gray-100 rounded p-2 bg-gray-50">
          {usage && <p className="text-gray-700">{usage}</p>}
          <div>
            <p className="font-semibold text-gray-500">Inputs</p>
            {inputs.length === 0 ? <p className="text-gray-400">none</p> : (
              <ul className="mt-0.5 space-y-0.5">
                {inputs.map(([name, spec]) => (
                  <li key={name}>
                    <span className="font-mono">{name}</span>
                    {spec?.required ? <span className="text-red-500"> *</span> : <span className="text-gray-400"> (optional)</span>}
                    {" — "}<span className="text-gray-500">{inputSource(name)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="font-semibold text-gray-500">Produces</p>
            <p className="mt-0.5">{outputs.length ? outputs.map((o) => <span key={o} className="font-mono mr-2">{o}</span>) : <span className="text-gray-400">—</span>}</p>
          </div>
          {mode && !mode.runnable && (
            <p className="text-amber-700">Dependencies: {mode.blocked_reason}</p>
          )}
        </div>
      )}
    </div>
  );
}

// Renders one skill result: status, outputs, and evidence.
function ResultBody({ r }: { r: SkillResult }) {
  return (
    <div>
      <span className={`text-xs px-2 py-0.5 rounded ${statusColor(r.status)}`}>{r.status}</span>
      {r.error && <p className="text-xs text-red-600 mt-1">{r.error}</p>}
      {r.outputs && Object.keys(r.outputs).length > 0 && (
        <div className="mt-2"><FormattedOutputs outputs={r.outputs} /></div>
      )}
      {r.evidence?.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-gray-500">Evidence ({r.evidence.length})</p>
          <ul className="mt-1 space-y-1">
            {r.evidence.map((ev, i) => (
              <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2">
                <span className="font-mono">{ev.document_id}</span>{ev.method ? ` · ${ev.method}` : ""}
                {ev.source_text ? ` — ${ev.source_text.slice(0, 140)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
