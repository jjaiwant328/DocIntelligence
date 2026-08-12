"use client";

import { useEffect, useState, useMemo } from "react";
import { apiCall } from "@/lib/api-config";
import type { DomainInfo } from "@/context/DomainContext";

interface SkillMeta { id: string; category: string; }
interface Step { id: string; skill: string; inputs_map?: Record<string, string>; }
interface Template { id: string; version?: string; approval_before?: string | null; steps: Step[]; source?: string; }
interface Evidence { document_id: string; source_text?: string; method?: string; }
interface StepRecord { id: string; skill: string; status: string; outputs: Record<string, unknown>; evidence: Evidence[]; error?: string | null; }
interface WorkflowRun { template_id: string; domain: string; status: string; work_object_id: string; halted_at?: string | null; steps: StepRecord[]; }

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];
function overlayDomain(d: string): string { return d === "supply_chain" ? "supply_chain" : "compliance"; }
function statusColor(s: string): string {
  if (["completed", "ok", "satisfied", "ASSIGNED", "CLOSED"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  if (["failed", "error"].includes(s)) return "bg-red-100 text-red-800";
  return "bg-blue-100 text-blue-800";
}

export default function WorkflowsTab({ domain }: { domain?: DomainInfo }) {
  const domainId = overlayDomain(domain?.domain_id ?? "compliance");
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState<string>("");
  const [name, setName] = useState<string>("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [approvalBefore, setApprovalBefore] = useState<string | null>(null);
  const [project, setProject] = useState(domainId === "supply_chain" ? "Supplier ABC" : "Store 1827");
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadTemplates = () =>
    apiCall<{ templates: Template[] }>(`/api/docintel/templates?domain_id=${domainId}`)
      .then((r) => setTemplates(r.templates || [])).catch((e) => setMsg(String(e)));

  useEffect(() => {
    apiCall<{ skills: SkillMeta[] }>("/api/docintel/skills").then((r) => setSkills(r.skills)).catch(() => {});
  }, []);
  useEffect(() => { loadTemplates(); /* eslint-disable-next-line */ }, [domainId]);

  function loadTemplate(id: string) {
    const t = templates.find((x) => x.id === id);
    setTid(id);
    if (t) {
      setName(t.source === "starter" ? `${t.id}_copy` : t.id);
      setSteps(t.steps.map((s) => ({ ...s })));
      setApprovalBefore(t.approval_before ?? null);
      setRun(null);
    }
  }

  function newTemplate() {
    setTid(""); setName("new_template"); setSteps([]); setApprovalBefore(null); setRun(null);
  }
  function addStep(skill: string) {
    const stepId = `${skill}_${steps.length + 1}`;
    setSteps((s) => [...s, { id: stepId, skill }]);
  }
  function move(i: number, dir: -1 | 1) {
    setSteps((s) => {
      const j = i + dir;
      if (j < 0 || j >= s.length) return s;
      const copy = [...s]; [copy[i], copy[j]] = [copy[j], copy[i]]; return copy;
    });
  }
  function removeStep(i: number) { setSteps((s) => s.filter((_, k) => k !== i)); }

  async function save() {
    if (!name || !steps.length) { setMsg("Name and at least one step required."); return; }
    setLoading(true); setMsg(null);
    try {
      const r = await apiCall<{ status?: string; error?: string }>("/api/docintel/templates", {
        method: "POST",
        body: JSON.stringify({
          template_id: name, domain_id: domainId, name,
          steps: steps.map((s) => ({ id: s.id, skill: s.skill })),
          approval_before: approvalBefore, autowire: true,
        }),
      });
      if (r.error) setMsg(`Save failed: ${r.error}`);
      else { setMsg(`Saved "${name}" for ${domainId}.`); await loadTemplates(); setTid(name); }
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }

  async function execute(approve: boolean) {
    if (!steps.length) return;
    setLoading(true); setMsg(null);
    try {
      // ensure the current canvas is saved so the engine runs exactly what's shown
      await save();
      const r = await apiCall<WorkflowRun>("/api/docintel/workflow-run", {
        method: "POST",
        body: JSON.stringify({ template: name, domain_id: domainId, project, approve }),
      });
      setRun(r);
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }

  const byCat = useMemo(() =>
    CATEGORY_ORDER.map((cat) => ({ cat, items: skills.filter((s) => s.category === cat) })).filter((g) => g.items.length),
    [skills]);

  return (
    <div className="px-4 py-4">
      <p className="text-sm text-gray-500 mb-3">
        Assemble skills into a workflow for <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>.
        Steps auto-wire by contract; save it per subject area and run it.
      </p>

      <div className="flex flex-wrap gap-3 items-end border border-gray-200 rounded-lg bg-white p-3 mb-4">
        <label className="flex flex-col text-xs text-gray-600">
          Template
          <select className="mt-1 border rounded px-2 py-1 text-sm min-w-[220px]" value={tid}
            onChange={(e) => loadTemplate(e.target.value)}>
            <option value="">— select —</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.id}{t.source === "starter" ? " (starter)" : ""}</option>)}
          </select>
        </label>
        <button onClick={newTemplate} className="text-sm border rounded px-3 py-1.5">+ New</button>
        <label className="flex flex-col text-xs text-gray-600">
          Name
          <input className="mt-1 border rounded px-2 py-1 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-gray-600">
          Project / Case
          <input className="mt-1 border rounded px-2 py-1 text-sm" value={project} onChange={(e) => setProject(e.target.value)} />
        </label>
        <button onClick={save} disabled={loading} className="text-sm bg-gray-800 text-white rounded px-3 py-1.5 disabled:opacity-50">Save</button>
        <button onClick={() => execute(false)} disabled={loading || !steps.length} className="text-sm bg-blue-600 text-white rounded px-3 py-1.5 disabled:opacity-50">Run ▶</button>
      </div>

      {msg && <div className="mb-3 text-xs text-gray-600 bg-gray-50 border rounded p-2">{msg}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* palette */}
        <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[60vh] overflow-y-auto">
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-2">Skill palette</p>
          {byCat.map((g) => (
            <div key={g.cat} className="mb-2">
              <p className="text-[10px] uppercase text-gray-400">{g.cat}</p>
              {g.items.map((s) => (
                <button key={s.id} onClick={() => addStep(s.id)}
                  className="block w-full text-left text-sm px-2 py-1 rounded hover:bg-gray-50">+ {s.id}</button>
              ))}
            </div>
          ))}
        </div>

        {/* canvas */}
        <div className="md:col-span-2 border border-gray-200 rounded-lg bg-white p-3 min-h-[200px]">
          {steps.length === 0 ? (
            <p className="text-sm text-gray-400">Click skills from the palette to add steps.</p>
          ) : (
            <ol className="space-y-2">
              {steps.map((s, i) => (
                <li key={i} className="flex items-center gap-2 border border-gray-100 rounded px-2 py-1.5">
                  <span className="text-xs font-mono text-gray-400 w-5">{i + 1}</span>
                  <span className="text-sm font-medium text-gray-800">{s.skill}</span>
                  {i > 0 && <span className="text-[10px] text-gray-400">⟵ auto-wired from prior steps</span>}
                  <span className="ml-auto flex items-center gap-1">
                    <button title="approval gate before this step"
                      onClick={() => setApprovalBefore(approvalBefore === s.skill ? null : s.skill)}
                      className={`text-[10px] px-1.5 py-0.5 rounded ${approvalBefore === s.skill ? "bg-amber-200 text-amber-800" : "bg-gray-100 text-gray-400"}`}>⛆ gate</button>
                    <button onClick={() => move(i, -1)} className="text-xs text-gray-400 px-1">↑</button>
                    <button onClick={() => move(i, 1)} className="text-xs text-gray-400 px-1">↓</button>
                    <button onClick={() => removeStep(i)} className="text-xs text-red-400 px-1">✕</button>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      {run && (
        <div className="mt-6">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-sm text-gray-600">{run.template_id} · {run.domain}{run.work_object_id ? ` · ${run.work_object_id}` : ""}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${statusColor(run.status)}`}>{run.status}</span>
          </div>
          {run.status === "pending_approval" && (
            <div className="mb-4 border border-amber-200 bg-amber-50 rounded p-3 text-sm">
              Halted at the approval gate.
              <button onClick={() => execute(true)} disabled={loading} className="ml-3 bg-amber-600 text-white rounded px-3 py-1 text-xs disabled:opacity-50">Approve &amp; continue</button>
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
