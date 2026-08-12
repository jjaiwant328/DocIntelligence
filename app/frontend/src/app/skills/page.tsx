"use client";

import { useEffect, useState, useMemo } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

/* ── types ─────────────────────────────────────────────────────────────── */
interface SkillMeta {
  id: string; category: string; enabled: boolean;
  description?: string; adapter?: string;
  inputs?: Record<string, { type?: string; required?: boolean }>;
  outputs?: Record<string, unknown>;
  side_effects?: Record<string, unknown>;
}
interface TemplateStep { id: string; skill: string; }
interface Template { id: string; version: string; approval_before?: string; steps: TemplateStep[]; }
interface Evidence { document_id: string; source_text?: string; method?: string; }
interface SkillResult { status: string; outputs: Record<string, unknown>; evidence: Evidence[]; error?: string | null; }
interface StepRecord { id: string; skill: string; status: string; outputs: Record<string, unknown>; evidence: Evidence[]; error?: string | null; }
interface WorkflowRun { template_id: string; domain: string; status: string; work_object_id: string; halted_at?: string | null; steps: StepRecord[]; }

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];
const SUB_TABS = [
  { id: "playground", label: "Skill Playground" },
  { id: "builder", label: "Workflow Builder" },
  { id: "runs", label: "Executions" },
];

/** Map the shell's subject-area domain_id to the overlay domain id. */
function overlayDomain(domainId: string): string {
  if (domainId === "supply_chain") return "supply_chain";
  return "compliance"; // compliance_due_diligence + any compliance variant
}

function statusColor(s: string): string {
  if (["completed", "ok", "satisfied", "ASSIGNED", "CLOSED"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  if (["failed", "error"].includes(s)) return "bg-red-100 text-red-800";
  if (["gap", "ESCALATED"].includes(s)) return "bg-orange-100 text-orange-800";
  if (s === "insufficient_evidence") return "bg-gray-200 text-gray-700";
  return "bg-blue-100 text-blue-800";
}

/* ── main component (driven entirely by the active subject area) ────────── */
export default function SkillsStudio({ domain }: { domain?: DomainInfo }) {
  const domainId = overlayDomain(domain?.domain_id ?? "compliance");
  const subjectLabel = domain?.name ?? domainId;
  const [tab, setTab] = useState("playground");

  return (
    <div className="px-4 py-4">
      <div className="mb-3">
        <p className="text-sm text-gray-500">
          Reusable skills &amp; deterministic workflows for{" "}
          <span className="font-semibold text-gray-700">{subjectLabel}</span>.
          Everything below runs against this subject area&apos;s corpus.
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-200 mb-4">
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`text-sm px-3 py-1.5 -mb-px border-b-2 ${tab === t.id ? "border-blue-600 text-blue-700 font-medium" : "border-transparent text-gray-500 hover:text-gray-700"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "playground" && <Playground domainId={domainId} />}
      {tab === "builder" && <Builder domainId={domainId} />}
      {tab === "runs" && <Executions />}
    </div>
  );
}

/* ── Skill Playground ──────────────────────────────────────────────────── */
function Playground({ domainId }: { domainId: string }) {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [selected, setSelected] = useState<SkillMeta | null>(null);
  const [inputsText, setInputsText] = useState("{}");
  const [result, setResult] = useState<SkillResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiCall<{ skills: SkillMeta[] }>("/api/docintel/skills")
      .then((r) => setSkills(r.skills))
      .catch((e) => setError(String(e)));
  }, []);

  function pick(s: SkillMeta) {
    setSelected(s); setResult(null); setError(null);
    const scaffold: Record<string, unknown> = {};
    Object.entries(s.inputs ?? {}).forEach(([k, spec]) => {
      if (spec.required) scaffold[k] = spec.type === "array" ? [] : "";
    });
    setInputsText(JSON.stringify(scaffold, null, 2));
  }

  async function invoke() {
    if (!selected) return;
    setLoading(true); setError(null);
    try {
      const inputs = JSON.parse(inputsText || "{}");
      const r = await apiCall<SkillResult>("/api/docintel/skill-invoke", {
        method: "POST",
        body: JSON.stringify({ skill: selected.id, domain_id: domainId, inputs }),
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
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[65vh] overflow-y-auto">
        {error && <div className="mb-2 text-xs text-red-600">{error}</div>}
        {byCat.map((g) => (
          <div key={g.cat} className="mb-3">
            <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{g.cat}</p>
            {g.items.map((s) => (
              <button key={s.id} onClick={() => pick(s)}
                className={`block w-full text-left text-sm px-2 py-1 rounded ${selected?.id === s.id ? "bg-blue-100 text-blue-800" : "hover:bg-gray-50"}`}>
                {s.id}
                {s.side_effects?.creates_actions ? <span className="ml-1 text-[10px] text-amber-600">✎</span> : null}
              </button>
            ))}
          </div>
        ))}
      </div>

      <div className="md:col-span-2">
        {!selected ? (
          <p className="text-sm text-gray-400">Select a skill to inspect and run it.</p>
        ) : (
          <div className="border border-gray-200 rounded-lg bg-white p-4">
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-gray-800">{selected.id}</h3>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{selected.adapter}</span>
            </div>
            <p className="text-sm text-gray-600 mt-1">{selected.description}</p>
            <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="font-semibold text-gray-500">Inputs</p>
                <ul className="mt-1">
                  {Object.entries(selected.inputs ?? {}).map(([k, spec]) => (
                    <li key={k} className="font-mono text-gray-600">{k}: {spec.type}{spec.required ? " *" : ""}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="font-semibold text-gray-500">Outputs</p>
                <ul className="mt-1">
                  {Object.keys(selected.outputs ?? {}).map((k) => (<li key={k} className="font-mono text-gray-600">{k}</li>))}
                </ul>
              </div>
            </div>
            <label className="block mt-3 text-xs text-gray-600">Inputs (JSON)</label>
            <textarea className="mt-1 w-full h-36 border rounded p-2 font-mono text-xs"
              value={inputsText} onChange={(e) => setInputsText(e.target.value)} />
            <button onClick={invoke} disabled={loading}
              className="mt-2 bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50">
              {loading ? "Invoking…" : "Invoke skill"}
            </button>
            {result && (
              <div className="mt-4">
                <span className={`text-xs px-2 py-0.5 rounded ${statusColor(result.status)}`}>{result.status}</span>
                {result.error && <p className="text-xs text-red-600 mt-1">{result.error}</p>}
                <pre className="mt-2 text-xs bg-gray-50 rounded p-2 overflow-x-auto">{JSON.stringify(result.outputs, null, 2)}</pre>
                {result.evidence?.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs font-semibold text-gray-500">Evidence ({result.evidence.length})</p>
                    <ul className="mt-1 space-y-1">
                      {result.evidence.map((ev, i) => (
                        <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2">
                          <span className="font-mono">{ev.document_id}</span>{ev.method ? ` · ${ev.method}` : ""}
                          {ev.source_text ? ` — ${ev.source_text.slice(0, 140)}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Workflow Builder ──────────────────────────────────────────────────── */
function Builder({ domainId }: { domainId: string }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState("");
  const [project, setProject] = useState(domainId === "supply_chain" ? "Supplier ABC" : "Store 1827");
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<{ templates: Template[] }>("/api/docintel/templates")
      .then((r) => { setTemplates(r.templates); if (r.templates.length) setTid(r.templates[0].id); })
      .catch((e) => setError(String(e)));
  }, []);

  const template = useMemo(() => templates.find((t) => t.id === tid) || null, [templates, tid]);

  async function execute(approve: boolean) {
    setLoading(true); setError(null);
    try {
      const r = await apiCall<WorkflowRun>("/api/docintel/workflow-run", {
        method: "POST",
        body: JSON.stringify({ template: tid, domain_id: domainId, project, approve }),
      });
      setRun(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  return (
    <div>
      {error && <div className="mb-3 border border-red-200 bg-red-50 text-red-700 text-sm rounded p-3">{error}</div>}
      <div className="border border-gray-200 rounded-lg bg-white p-4 flex flex-wrap gap-3 items-end">
        <label className="flex flex-col text-xs text-gray-600">
          Template
          <select className="mt-1 border rounded px-2 py-1 text-sm min-w-[220px]" value={tid} onChange={(e) => setTid(e.target.value)}>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.id} (v{t.version})</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Project / Case
          <input className="mt-1 border rounded px-2 py-1 text-sm" value={project} onChange={(e) => setProject(e.target.value)} />
        </label>
        <button onClick={() => execute(false)} disabled={loading || !tid}
          className="bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50">
          {loading ? "Running…" : "Run"}
        </button>
      </div>

      {template && (
        <div className="mt-4 border border-gray-200 rounded-lg bg-white p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400 mb-2">Steps ({template.steps.length})</p>
          <ol className="flex flex-wrap gap-2">
            {template.steps.map((s, i) => (
              <li key={s.id} className="text-xs">
                <span className="px-2 py-1 rounded bg-gray-100 text-gray-700 font-mono">{i + 1}. {s.skill}</span>
                {template.approval_before === s.skill && <span className="ml-1 text-[10px] text-amber-600">⛆ gate</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {run && (
        <div className="mt-6">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-sm text-gray-600">{run.template_id} · {run.domain}{run.work_object_id ? ` · ${run.work_object_id}` : ""}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${statusColor(run.status)}`}>{run.status}</span>
          </div>
          {run.status === "pending_approval" && (
            <div className="mb-4 border border-amber-200 bg-amber-50 rounded p-3 text-sm">
              Halted at the approval gate before creating actions.
              <button onClick={() => execute(true)} disabled={loading}
                className="ml-3 bg-amber-600 text-white rounded px-3 py-1 text-xs disabled:opacity-50">Approve &amp; continue</button>
            </div>
          )}
          <ol className="space-y-2">
            {run.steps.map((s) => (
              <li key={s.id} className="border border-gray-200 rounded-lg bg-white px-4 py-2">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs text-gray-400">{s.id}</span>
                  <span className="text-sm font-medium text-gray-800">{s.skill}</span>
                  <span className={`ml-auto text-xs px-2 py-0.5 rounded ${statusColor(s.status)}`}>{s.status}</span>
                  <span className="text-xs text-gray-400">{s.evidence.length} ev</span>
                </div>
                {s.error && <p className="text-xs text-red-600 mt-1">{s.error}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

/* ── Executions (observability) ────────────────────────────────────────── */
function Executions() {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    apiCall<{ executions: Record<string, unknown>[] }>("/api/docintel/skill-executions?limit=50")
      .then((r) => setRows(r.executions))
      .catch((e) => setError(String(e)));
  }
  useEffect(refresh, []);

  return (
    <div>
      <button onClick={refresh} className="text-xs text-blue-600 mb-2">↻ Refresh</button>
      {error && <div className="text-xs text-red-600 mb-2">{error}</div>}
      <div className="border border-gray-200 rounded-lg bg-white overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="text-left px-2 py-1">skill</th><th className="text-left px-2 py-1">status</th>
              <th className="text-left px-2 py-1">workflow</th><th className="text-left px-2 py-1">evidence</th>
              <th className="text-left px-2 py-1">start</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-gray-100">
                <td className="px-2 py-1 font-mono">{String(r.skill_id)}</td>
                <td className="px-2 py-1"><span className={`px-1.5 py-0.5 rounded ${statusColor(String(r.status))}`}>{String(r.status)}</span></td>
                <td className="px-2 py-1">{String(r.workflow_id || "—")}</td>
                <td className="px-2 py-1">{String(r.evidence_count ?? 0)}</td>
                <td className="px-2 py-1 text-gray-400">{String(r.start_time || "").slice(0, 19)}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={5} className="px-2 py-3 text-gray-400 text-center">No executions yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
