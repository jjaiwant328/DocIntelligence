"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { apiCall } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";
import { FormattedOutputs } from "@/components/FormattedOutputs";

interface InputSpec { type?: string; required?: boolean }
interface SkillMeta {
  id: string; category: string; description?: string;
  inputs?: Record<string, InputSpec>;
  outputs?: Record<string, unknown>;
  mode?: { runnable: boolean; runnable_on_docs: boolean; needs_docs: boolean; blocked_reason: string };
}
interface Step { id: string; skill: string; inputs_map?: Record<string, string>; }
interface Template { id: string; version?: string; approval_before?: string | null; steps: Step[]; source?: string; }
interface Evidence { document_id: string; source_text?: string; method?: string; }
interface StepRecord { id: string; skill: string; status: string; outputs: Record<string, unknown>; evidence: Evidence[]; error?: string | null; }
interface WorkflowRun { template_id: string; domain: string; status: string; work_object_id: string; halted_at?: string | null; steps: StepRecord[]; saved?: boolean; run_id?: string; }

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];
// Mirror of skill_runtime/autowire.py resolution rules — keep in sync so the
// assembler warns about exactly what the engine would reject at run time.
const DOMAIN_KEYS = new Set(["requirements"]);
const DOMAIN_ALIASES: Record<string, string> = { candidate_requirements: "requirements" };
const INPUT_KEYS = new Set(["domain", "project", "schema_vec", "approve"]);
// Inputs fed from the workflow's document set ($docs.*).
const DOC_KEYS = new Set(["text", "context", "current", "previous", "conclusion", "query"]);

interface StepIssue { step: number; skill: string; missing: string[]; needsDocs: boolean }
// For each step, a required input is satisfiable if a prior step outputs a key
// of the same name, or it maps to a domain-config / workflow input / the doc set.
// A doc-fed input is only "missing" when no documents are available for the run.
function validateSteps(steps: Step[], byId: Record<string, SkillMeta>, hasDocs: boolean): StepIssue[] {
  const issues: StepIssue[] = [];
  const priorOutputs = new Set<string>();
  steps.forEach((s, i) => {
    const meta = byId[s.skill];
    const inputs = meta?.inputs ?? {};
    let needsDocs = false;
    const missing = Object.entries(inputs)
      .filter(([, spec]) => spec?.required)
      .map(([name]) => name)
      .filter((name) => {
        if (priorOutputs.has(name) || name in DOMAIN_ALIASES ||
            DOMAIN_KEYS.has(name) || INPUT_KEYS.has(name)) return false;
        if (DOC_KEYS.has(name)) {
          if (hasDocs) return false;   // satisfied by the document set
          needsDocs = true;
          return true;                 // no docs → this will fail
        }
        return true;
      });
    if (missing.length) issues.push({ step: i + 1, skill: s.skill, missing, needsDocs });
    Object.keys(meta?.outputs ?? {}).forEach((k) => priorOutputs.add(k));
  });
  return issues;
}
function overlayDomain(d: string): string { return d === "supply_chain" ? "supply_chain" : "compliance"; }
// Rich hover text for a palette skill: what it does, produces, and any dependency.
function paletteTooltip(s: SkillMeta): string {
  const parts: string[] = [];
  if (s.description) parts.push(s.description);
  const produces = Object.keys(s.outputs ?? {}).filter((k) => k !== "evidence");
  if (produces.length) parts.push("Produces: " + produces.join(", "));
  if (s.mode && !s.mode.runnable) parts.push("Dependency: " + s.mode.blocked_reason);
  return parts.join("\n");
}

// Specific, actionable guidance for an unsatisfied required input.
const DOC_FED = new Set(["text", "context", "current", "previous", "conclusion", "query"]);
// input name -> the step whose output produces it (for "add step X" hints)
const PRODUCED_BY: Record<string, string> = {
  gaps: "identify_gap", assessments: "assess_requirement", risk: "assess_risk",
  findings: "create_finding", recommendation: "generate_recommendation",
  proposed_actions: "generate_recommendation", changes: "detect_change",
  events: "build_timeline", evidence: "find_supporting_evidence",
  work_object_id: "create_work_object", action_id: "create_action",
};
function guidanceFor(input: string, needsDocs: boolean): string {
  if (DOC_FED.has(input)) {
    return needsDocs
      ? `“${input}” comes from the run's documents, but none are selected. Open “Documents” above and select at least one (or pick a project in the header that has tagged documents).`
      : `“${input}” is filled from the selected documents.`;
  }
  if (PRODUCED_BY[input]) {
    return `“${input}” is produced by the “${PRODUCED_BY[input]}” skill. Drag that skill in as an earlier step, then this step auto-wires to it.`;
  }
  return `“${input}” isn't produced by any earlier step. Add a step that outputs “${input}” before this one, or remove this step.`;
}
function statusColor(s: string): string {
  if (["completed", "ok", "satisfied", "ASSIGNED", "CLOSED"].includes(s)) return "bg-green-100 text-green-800";
  if (s === "pending_approval") return "bg-amber-100 text-amber-800";
  if (["failed", "error"].includes(s)) return "bg-red-100 text-red-800";
  return "bg-blue-100 text-blue-800";
}

export default function WorkflowsTab({ domain }: { domain?: DomainInfo }) {
  const { project: ctxProject } = useDomain();
  const domainId = overlayDomain(domain?.domain_id ?? "compliance");
  // The run's project id comes from the shared project picker; fall back to a
  // sensible default when no project is selected so a run still works.
  const project = ctxProject?.project_id
    ?? (domainId === "supply_chain" ? "Supplier ABC" : "Store 1827");
  const projectLabel = ctxProject?.name || project;
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState<string>("");
  const [name, setName] = useState<string>("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [approvalBefore, setApprovalBefore] = useState<string | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const resultRef = useRef<HTMLDivElement | null>(null);
  // drag-and-drop: a palette skill ("new:<id>") or an existing step index being dragged
  const [drag, setDrag] = useState<{ kind: "palette"; skill: string } | { kind: "step"; index: number } | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  // the workflow's document set (this project's tagged docs), + optional narrowing
  const [docs, setDocs] = useState<{ doc_id: string; doc_type?: string }[]>([]);
  const [docChecked, setDocChecked] = useState<Record<string, boolean>>({});
  const [showDocPicker, setShowDocPicker] = useState(false);

  function handleDrop(index: number) {
    if (!drag) return;
    if (drag.kind === "palette") insertStep(drag.skill, index);
    else reorder(drag.index, index > drag.index ? index - 1 : index);
    setDrag(null); setDropAt(null);
  }

  const loadTemplates = () =>
    apiCall<{ templates: Template[] }>(`/api/docintel/templates?domain_id=${domainId}`)
      .then((r) => setTemplates(r.templates || [])).catch((e) => setMsg(String(e)));

  useEffect(() => {
    apiCall<{ skills: SkillMeta[] }>("/api/docintel/skills").then((r) => setSkills(r.skills)).catch(() => {});
  }, []);
  useEffect(() => { loadTemplates(); /* eslint-disable-next-line */ }, [domainId]);

  // load the project's document set (drives $docs.* and the "narrow" picker)
  useEffect(() => {
    const q = `/api/docintel/parsed-documents?domain_id=${domainId}` +
      (ctxProject?.project_id ? `&project_id=${encodeURIComponent(ctxProject.project_id)}` : "");
    apiCall<{ documents: { doc_id: string; doc_type?: string }[] }>(q)
      .then((r) => {
        setDocs(r.documents || []);
        const all: Record<string, boolean> = {};
        (r.documents || []).forEach((d) => { all[d.doc_id] = true; });
        setDocChecked(all);
      })
      .catch(() => { setDocs([]); setDocChecked({}); });
  }, [domainId, ctxProject?.project_id]);

  const selectedDocIds = docs.filter((d) => docChecked[d.doc_id]).map((d) => d.doc_id);
  const hasDocs = selectedDocIds.length > 0;

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
    setSteps((s) => [...s, { id: `${skill}_${s.length + 1}`, skill }]);
  }
  function insertStep(skill: string, index: number) {
    setSteps((s) => {
      const copy = [...s];
      const id = `${skill}_${s.length + 1}`;
      copy.splice(Math.max(0, Math.min(index, copy.length)), 0, { id, skill });
      return copy;
    });
  }
  function move(i: number, dir: -1 | 1) {
    setSteps((s) => {
      const j = i + dir;
      if (j < 0 || j >= s.length) return s;
      const copy = [...s]; [copy[i], copy[j]] = [copy[j], copy[i]]; return copy;
    });
  }
  function reorder(from: number, to: number) {
    setSteps((s) => {
      if (from === to || from < 0 || from >= s.length) return s;
      const copy = [...s];
      const [item] = copy.splice(from, 1);
      copy.splice(Math.max(0, Math.min(to, copy.length)), 0, item);
      return copy;
    });
  }
  function removeStep(i: number) { setSteps((s) => s.filter((_, k) => k !== i)); }

  async function save(partOfRun = false) {
    if (!name || !steps.length) { setMsg("Name and at least one step required."); return false; }
    setLoading(true);
    if (!partOfRun) { setBusy("save"); setMsg("Saving… (waking the SQL warehouse may take up to a minute)"); }
    try {
      const r = await apiCall<{ status?: string; error?: string }>("/api/docintel/templates", {
        method: "POST",
        body: JSON.stringify({
          template_id: name, domain_id: domainId, name,
          steps: steps.map((s) => ({ id: s.id, skill: s.skill })),
          approval_before: approvalBefore, autowire: true,
        }),
      });
      if (r.error) { setMsg(`Save failed: ${r.error}`); return false; }
      if (!partOfRun) { setMsg(`Saved "${name}" for ${domainId}.`); await loadTemplates(); setTid(name); }
      return true;
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); return false; }
    finally { if (!partOfRun) { setLoading(false); setBusy(null); } }
  }

  async function execute(approve: boolean) {
    if (!steps.length) return;
    setLoading(true); setBusy("run");
    setMsg("Running… (waking the SQL warehouse may take up to a minute)");
    try {
      // ensure the current canvas is saved so the engine runs exactly what's shown
      const saved = await save(true);
      if (!saved) return;   // save() already surfaced the error
      const r = await apiCall<WorkflowRun>("/api/docintel/workflow-run", {
        method: "POST",
        body: JSON.stringify({ template: name, domain_id: domainId, project, approve,
          doc_ids: hasDocs ? selectedDocIds : undefined,
          label: `${name} · ${projectLabel}` }),
      });
      setRun(r);
      // the run auto-saved this workflow — make it visible in the template list
      await loadTemplates(); setTid(name);
      const failed = (r.steps || []).find((s) => s.status === "error");
      setMsg(r.status === "pending_approval"
        ? "Run halted at the approval gate — approve below to continue."
        : failed
          ? `Run ${r.status}: step "${failed.skill}" — ${failed.error}`
          : `Run ${r.status}. Saved to Executions — see results below.`);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); setBusy(null); }
  }

  const byCat = useMemo(() =>
    CATEGORY_ORDER.map((cat) => ({ cat, items: skills.filter((s) => s.category === cat) })).filter((g) => g.items.length),
    [skills]);

  const byId = useMemo(() => Object.fromEntries(skills.map((s) => [s.id, s])), [skills]);
  const issues = useMemo(() => validateSteps(steps, byId, hasDocs), [steps, byId, hasDocs]);
  const issueByStep = useMemo(() => {
    const m: Record<number, string[]> = {};
    issues.forEach((it) => { m[it.step] = it.missing; });
    return m;
  }, [issues]);

  return (
    <div className="px-4 py-4">
      <p className="text-sm text-gray-500 mb-3">
        Assemble skills into a workflow for <span className="font-semibold text-gray-700">{domain?.name ?? domainId}</span>
        {ctxProject?.project_id
          ? <> · project <span className="font-semibold text-gray-700">📁 {projectLabel}</span></>
          : <> · <span className="italic">no project selected (pick one in the header)</span></>}.
        Steps auto-wire by contract; save it per subject area and run it — every run is saved to Executions.
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
        <div className="flex flex-col text-xs text-gray-600">
          Project / Case
          <span className="mt-1 border rounded px-2 py-1.5 text-sm bg-gray-50 text-gray-700 min-w-[140px]">
            📁 {projectLabel}
          </span>
        </div>
        <div className="flex flex-col text-xs text-gray-600">
          Documents
          <button onClick={() => setShowDocPicker((v) => !v)}
            title="The document set this workflow runs on. Click to narrow to a subset."
            className="mt-1 border rounded px-2 py-1.5 text-sm bg-white hover:bg-gray-50 min-w-[140px] text-left">
            📎 {selectedDocIds.length} of {docs.length} {showDocPicker ? "▾" : "▸"}
          </button>
        </div>
        <button onClick={() => save()} disabled={loading} className="text-sm bg-gray-800 text-white rounded px-3 py-1.5 disabled:opacity-50">
          {busy === "save" ? "Saving…" : "Save"}
        </button>
        <button onClick={() => execute(false)} disabled={loading || !steps.length}
          title={issues.length ? "This workflow has missing inputs and will halt — run anyway to see where." : undefined}
          className={`text-sm text-white rounded px-3 py-1.5 disabled:opacity-50 ${issues.length ? "bg-amber-600" : "bg-blue-600"}`}>
          {busy === "run" ? "Running…" : issues.length ? "Run anyway ▶" : "Run ▶"}
        </button>
        <span className="text-xs text-gray-500 self-center">Every run is auto-saved to Executions.</span>
      </div>

      {showDocPicker && (
        <div className="mb-4 border border-gray-200 rounded-lg bg-white p-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-600">
              Document set for this run{ctxProject?.project_id ? <> — project <span className="font-medium">📁 {projectLabel}</span></> : null}.
              Document-reading steps (classify, summarize…) use these.
            </p>
            <span className="flex gap-2">
              <button onClick={() => setDocChecked(Object.fromEntries(docs.map((d) => [d.doc_id, true])))}
                className="text-xs text-blue-600">Select all</button>
              <button onClick={() => setDocChecked({})} className="text-xs text-gray-400">Clear</button>
            </span>
          </div>
          {docs.length === 0 ? (
            <p className="text-xs text-gray-400">
              No documents{ctxProject?.project_id ? " tagged to this project" : ""} yet.
              Tag documents to a project in the Document Library, or pick a project in the header.
            </p>
          ) : (
            <div className="max-h-48 overflow-y-auto border rounded">
              {docs.map((d) => (
                <label key={d.doc_id} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-gray-50 last:border-0">
                  <input type="checkbox" checked={!!docChecked[d.doc_id]}
                    onChange={(e) => setDocChecked((c) => ({ ...c, [d.doc_id]: e.target.checked }))} />
                  <span className="font-mono truncate">{d.doc_id}</span>
                  {d.doc_type && <span className="ml-auto text-gray-400">{d.doc_type}</span>}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {msg && (
        <div className={`mb-3 text-sm border rounded p-2 flex items-center gap-2 ${
          busy ? "bg-blue-50 border-blue-200 text-blue-800"
          : /fail|error|missing/i.test(msg) ? "bg-red-50 border-red-200 text-red-800"
          : "bg-green-50 border-green-200 text-green-800"}`}>
          {busy && <span className="inline-block h-3 w-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />}
          {msg}
        </div>
      )}

      {issues.length > 0 && (
        <div className="mb-3 text-xs bg-amber-50 border border-amber-200 rounded p-2 text-amber-800">
          <span className="font-semibold">⚠ Missing inputs — this workflow will halt at run time.</span>{" "}
          <span className="text-amber-600">Hover each input for how to fix it.</span>
          <ul className="mt-1 space-y-1">
            {issues.map((it) => (
              <li key={it.step}>
                Step {it.step} <span className="font-mono">{it.skill}</span> needs{" "}
                {it.missing.map((name, k) => (
                  <span key={name}>
                    <span className="group relative inline-block">
                      <span className="font-mono underline decoration-dotted cursor-help">{name}</span>
                      <span className="pointer-events-none absolute bottom-full left-0 mb-1 w-72 bg-gray-900 text-white text-[11px] rounded-lg px-3 py-2 leading-snug opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
                        {guidanceFor(name, it.needsDocs)}
                      </span>
                    </span>
                    {k < it.missing.length - 1 ? ", " : ""}
                  </span>
                ))}
                {it.needsDocs && (
                  <button onClick={() => setShowDocPicker(true)} className="ml-2 underline text-amber-700">select documents</button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* palette */}
        <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[60vh] overflow-y-auto">
          <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-2">Skill palette</p>
          <p className="text-[10px] text-gray-400 mb-2">Click to append, or drag onto the canvas to drop at a position.</p>
          {byCat.map((g) => (
            <div key={g.cat} className="mb-2">
              <p className="text-[10px] uppercase text-gray-400">{g.cat}</p>
              {g.items.map((s) => (
                <button key={s.id} onClick={() => addStep(s.id)}
                  draggable
                  onDragStart={() => setDrag({ kind: "palette", skill: s.id })}
                  onDragEnd={() => { setDrag(null); setDropAt(null); }}
                  title={paletteTooltip(s)}
                  className="flex items-center gap-1 w-full text-left text-sm px-2 py-1 rounded hover:bg-gray-50 cursor-grab active:cursor-grabbing">
                  <span className="text-gray-300">⠿</span> + {s.id}
                  {s.mode && !s.mode.runnable_on_docs && (
                    <span className="ml-auto text-[9px] text-gray-400">
                      {s.mode.runnable ? "input" : "needs prior step"}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* canvas */}
        <div className="md:col-span-2 border border-gray-200 rounded-lg bg-white p-3 min-h-[200px]"
          onDragOver={(e) => { if (drag) { e.preventDefault(); if (steps.length === 0) setDropAt(0); } }}
          onDrop={(e) => { e.preventDefault(); handleDrop(dropAt ?? steps.length); }}>
          {steps.length === 0 ? (
            <p className={`text-sm ${drag ? "text-blue-500" : "text-gray-400"}`}>
              {drag ? "Drop here to add the first step." : "Click or drag skills from the palette to add steps."}
            </p>
          ) : (
            <ol className="space-y-0">
              {steps.map((s, i) => (
                <div key={s.id}>
                  {/* drop zone above step i */}
                  <div
                    onDragOver={(e) => { if (drag) { e.preventDefault(); setDropAt(i); } }}
                    onDrop={(e) => { e.preventDefault(); handleDrop(i); }}
                    className={`h-2 -my-0.5 rounded transition-colors ${dropAt === i && drag ? "bg-blue-300 h-3" : ""}`}
                  />
                  <li
                    draggable
                    onDragStart={() => setDrag({ kind: "step", index: i })}
                    onDragEnd={() => { setDrag(null); setDropAt(null); }}
                    className={`flex items-center gap-2 border rounded px-2 py-1.5 bg-white cursor-grab active:cursor-grabbing ${issueByStep[i + 1] ? "border-amber-300 bg-amber-50" : "border-gray-100"} ${drag?.kind === "step" && drag.index === i ? "opacity-40" : ""}`}>
                    <span className="text-gray-300">⠿</span>
                    <span className="text-xs font-mono text-gray-400 w-5">{i + 1}</span>
                    <span className="text-sm font-medium text-gray-800">{s.skill}</span>
                    {issueByStep[i + 1] ? (
                      <span className="text-[10px] text-amber-700" title={`missing: ${issueByStep[i + 1].join(", ")}`}>
                        ⚠ needs {issueByStep[i + 1].join(", ")}
                      </span>
                    ) : i > 0 ? (
                      <span className="text-[10px] text-gray-400">⟵ auto-wired from prior steps</span>
                    ) : null}
                    <span className="ml-auto flex items-center gap-1">
                      <button title="approval gate before this step"
                        onClick={() => setApprovalBefore(approvalBefore === s.skill ? null : s.skill)}
                        className={`text-[10px] px-1.5 py-0.5 rounded ${approvalBefore === s.skill ? "bg-amber-200 text-amber-800" : "bg-gray-100 text-gray-400"}`}>⛆ gate</button>
                      <button onClick={() => move(i, -1)} title="move up" className="text-xs text-gray-400 px-1">↑</button>
                      <button onClick={() => move(i, 1)} title="move down" className="text-xs text-gray-400 px-1">↓</button>
                      <button onClick={() => removeStep(i)} className="text-xs text-red-400 px-1">✕</button>
                    </span>
                  </li>
                </div>
              ))}
              {/* drop zone at the end */}
              <div
                onDragOver={(e) => { if (drag) { e.preventDefault(); setDropAt(steps.length); } }}
                onDrop={(e) => { e.preventDefault(); handleDrop(steps.length); }}
                className={`h-3 mt-1 rounded transition-colors ${dropAt === steps.length && drag ? "bg-blue-300" : ""}`}
              />
            </ol>
          )}
        </div>
      </div>

      {run && (
        <div className="mt-6" ref={resultRef}>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Run result</h3>
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <span className="text-sm font-medium text-gray-800">📁 {project}</span>
            <span className="text-xs text-gray-500">{run.template_id} · {run.domain}{run.work_object_id ? ` · ${run.work_object_id}` : ""}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${statusColor(run.status)}`}>{run.status}</span>
            {run.run_id && (
              <a href="/executions" className="text-xs text-blue-600 hover:underline">View full execution in Executions →</a>
            )}
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
                {s.outputs && Object.keys(s.outputs).length > 0 && (
                  <FormattedOutputs skill={s.skill} outputs={s.outputs} />
                )}
                {s.evidence?.length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {s.evidence.slice(0, 4).map((ev, k) => (
                      <li key={k} className="text-[11px] text-gray-500 border-l-2 border-blue-200 pl-2">
                        <span className="font-mono">{ev.document_id}</span>
                        {ev.source_text ? ` — ${ev.source_text.slice(0, 120)}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
