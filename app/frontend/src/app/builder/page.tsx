"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";

interface TemplateStep { id: string; skill: string; }
interface Template { id: string; version: string; approval_before?: string; steps: TemplateStep[]; }
interface StepRecord {
  id: string; skill: string; status: string;
  outputs: Record<string, unknown>;
  evidence: { document_id: string; source_text?: string; method?: string }[];
  error?: string | null;
}
interface WorkflowRun {
  template_id: string; domain: string; status: string;
  work_object_id: string; halted_at?: string | null; steps: StepRecord[];
}

const DOMAINS = [
  { id: "compliance", project: "Store 1827" },
  { id: "supply_chain", project: "Supplier ABC" },
];

function statusColor(s: string): string {
  if (["completed", "ok", "satisfied"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  if (["failed", "error"].includes(s)) return "bg-red-100 text-red-800";
  return "bg-blue-100 text-blue-800";
}

export default function BuilderPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState<string>("");
  const [domainId, setDomainId] = useState("compliance");
  const [project, setProject] = useState("Store 1827");
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<{ templates: Template[] }>("/api/docintel/templates")
      .then((r) => {
        setTemplates(r.templates);
        if (r.templates.length) setTid(r.templates[0].id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const template = templates.find((t) => t.id === tid) || null;

  async function execute(approve: boolean) {
    setLoading(true);
    setError(null);
    try {
      const r = await apiCall<WorkflowRun>("/api/docintel/workflow-run", {
        method: "POST",
        body: JSON.stringify({ template: tid, domain_id: domainId, project, approve }),
      });
      setRun(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-gray-800">Workflow Builder</h1>
      <p className="text-sm text-gray-500 mb-4">
        Pick a template, review its skill steps, configure a domain + project, and run it.
        The same templates run any domain with no code change.
      </p>

      {error && <div className="mb-3 border border-red-200 bg-red-50 text-red-700 text-sm rounded p-3">{error}</div>}

      <div className="border border-gray-200 rounded-lg bg-white p-4 flex flex-wrap gap-3 items-end">
        <label className="flex flex-col text-xs text-gray-600">
          Template
          <select className="mt-1 border rounded px-2 py-1 text-sm min-w-[220px]" value={tid} onChange={(e) => setTid(e.target.value)}>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.id} (v{t.version})</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Domain
          <select className="mt-1 border rounded px-2 py-1 text-sm" value={domainId}
            onChange={(e) => { const d = DOMAINS.find((x) => x.id === e.target.value)!; setDomainId(d.id); setProject(d.project); }}>
            {DOMAINS.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Project / Case
          <input className="mt-1 border rounded px-2 py-1 text-sm" value={project} onChange={(e) => setProject(e.target.value)} />
        </label>
        <button onClick={() => execute(false)} disabled={loading || !tid} className="bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50">
          {loading ? "Running…" : "Run"}
        </button>
      </div>

      {/* Step graph preview */}
      {template && (
        <div className="mt-4 border border-gray-200 rounded-lg bg-white p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400 mb-2">Steps ({template.steps.length})</p>
          <ol className="flex flex-wrap gap-2">
            {template.steps.map((s, i) => (
              <li key={s.id} className="text-xs">
                <span className="px-2 py-1 rounded bg-gray-100 text-gray-700 font-mono">
                  {i + 1}. {s.skill}
                </span>
                {template.approval_before === s.skill && (
                  <span className="ml-1 text-[10px] text-amber-600">⛆ approval gate</span>
                )}
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
              <button onClick={() => execute(true)} disabled={loading} className="ml-3 bg-amber-600 text-white rounded px-3 py-1 text-xs disabled:opacity-50">
                Approve &amp; continue
              </button>
            </div>
          )}
          <ol className="space-y-2">
            {run.steps.map((s) => (
              <li key={s.id} className="border border-gray-200 rounded-lg bg-white px-4 py-2">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs text-gray-400">{s.id}</span>
                  <span className="text-sm font-medium text-gray-800">{s.skill}</span>
                  <span className={`ml-auto text-xs px-2 py-0.5 rounded ${statusColor(s.status)}`}>{s.status}</span>
                  <span className="text-xs text-gray-400">{s.evidence.length} evidence</span>
                </div>
                {s.error && <p className="text-xs text-red-600 mt-1">{s.error}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </main>
  );
}
