"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";

interface SkillMeta {
  id: string;
  category: string;
  enabled: boolean;
  description?: string;
  adapter?: string;
  inputs?: Record<string, { type?: string; required?: boolean }>;
  outputs?: Record<string, unknown>;
  side_effects?: Record<string, unknown>;
}
interface SkillsResp { skills: SkillMeta[]; enabled: string[]; }
interface SkillResult {
  status: string;
  outputs: Record<string, unknown>;
  evidence: { document_id: string; source_text?: string; method?: string }[];
  error?: string | null;
}

const CATEGORY_ORDER = ["understanding", "retrieval", "reasoning", "workflow", "communication"];

export default function PlaygroundPage() {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [selected, setSelected] = useState<SkillMeta | null>(null);
  const [domainId, setDomainId] = useState("compliance");
  const [inputsText, setInputsText] = useState("{}");
  const [result, setResult] = useState<SkillResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiCall<SkillsResp>("/api/docintel/skills")
      .then((r) => setSkills(r.skills))
      .catch((e) => setError(String(e)));
  }, []);

  function pick(s: SkillMeta) {
    setSelected(s);
    setResult(null);
    setError(null);
    const scaffold: Record<string, unknown> = {};
    Object.entries(s.inputs ?? {}).forEach(([k, spec]) => {
      if (spec.required) scaffold[k] = spec.type === "array" ? [] : "";
    });
    setInputsText(JSON.stringify(scaffold, null, 2));
  }

  async function invoke() {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const inputs = JSON.parse(inputsText || "{}");
      const r = await apiCall<SkillResult>("/api/docintel/skill-invoke", {
        method: "POST",
        body: JSON.stringify({ skill: selected.id, domain_id: domainId, inputs }),
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const byCat = CATEGORY_ORDER.map((cat) => ({
    cat,
    items: skills.filter((s) => s.category === cat),
  })).filter((g) => g.items.length);

  return (
    <main className="max-w-6xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-gray-800">Skill Playground</h1>
      <p className="text-sm text-gray-500 mb-4">
        Invoke any registered skill directly, with typed inputs and evidence-backed output.
      </p>

      {error && <div className="mb-3 border border-red-200 bg-red-50 text-red-700 text-sm rounded p-3">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Skill list */}
        <div className="md:col-span-1 border border-gray-200 rounded-lg bg-white p-3 max-h-[70vh] overflow-y-auto">
          {byCat.map((g) => (
            <div key={g.cat} className="mb-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-400 mb-1">{g.cat}</p>
              {g.items.map((s) => (
                <button
                  key={s.id}
                  onClick={() => pick(s)}
                  className={`block w-full text-left text-sm px-2 py-1 rounded ${selected?.id === s.id ? "bg-blue-100 text-blue-800" : "hover:bg-gray-50"}`}
                >
                  {s.id}
                  {s.side_effects?.creates_actions ? <span className="ml-1 text-[10px] text-amber-600">✎ writes</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* Detail + invoke */}
        <div className="md:col-span-2">
          {!selected ? (
            <p className="text-sm text-gray-400">Select a skill to inspect and run it.</p>
          ) : (
            <div className="border border-gray-200 rounded-lg bg-white p-4">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-gray-800">{selected.id}</h2>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{selected.adapter}</span>
              </div>
              <p className="text-sm text-gray-600 mt-1">{selected.description}</p>

              <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="font-semibold text-gray-500">Inputs</p>
                  <ul className="mt-1">
                    {Object.entries(selected.inputs ?? {}).map(([k, spec]) => (
                      <li key={k} className="font-mono text-gray-600">
                        {k}: {spec.type}{spec.required ? " *" : ""}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="font-semibold text-gray-500">Outputs</p>
                  <ul className="mt-1">
                    {Object.keys(selected.outputs ?? {}).map((k) => (
                      <li key={k} className="font-mono text-gray-600">{k}</li>
                    ))}
                  </ul>
                </div>
              </div>

              <label className="block mt-3 text-xs text-gray-600">
                Domain
                <select className="ml-2 border rounded px-2 py-0.5 text-sm" value={domainId} onChange={(e) => setDomainId(e.target.value)}>
                  <option value="compliance">compliance</option>
                  <option value="supply_chain">supply_chain</option>
                </select>
              </label>

              <label className="block mt-3 text-xs text-gray-600">Inputs (JSON)</label>
              <textarea
                className="mt-1 w-full h-40 border rounded p-2 font-mono text-xs"
                value={inputsText}
                onChange={(e) => setInputsText(e.target.value)}
              />

              <button
                onClick={invoke}
                disabled={loading}
                className="mt-2 bg-blue-600 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50"
              >
                {loading ? "Invoking…" : "Invoke skill"}
              </button>

              {result && (
                <div className="mt-4">
                  <span className={`text-xs px-2 py-0.5 rounded ${result.status === "error" ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800"}`}>
                    {result.status}
                  </span>
                  {result.error && <p className="text-xs text-red-600 mt-1">{result.error}</p>}
                  <pre className="mt-2 text-xs bg-gray-50 rounded p-2 overflow-x-auto">{JSON.stringify(result.outputs, null, 2)}</pre>
                  {result.evidence?.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs font-semibold text-gray-500">Evidence ({result.evidence.length})</p>
                      <ul className="mt-1 space-y-1">
                        {result.evidence.map((ev, i) => (
                          <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2">
                            <span className="font-mono">{ev.document_id}</span>
                            {ev.method ? ` · ${ev.method}` : ""}
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
    </main>
  );
}
