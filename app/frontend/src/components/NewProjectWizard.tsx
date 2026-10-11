"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";

interface Blueprint { id: string; name: string; description?: string }
interface ProvisionStep { step: string; status: string; error?: string }
interface ProvisionResult { ok: boolean; use_case_id: string; name: string; steps?: ProvisionStep[]; error?: string }

/**
 * Stand up a whole use case ("Project") from a declarative Blueprint in one call —
 * the citizen-developer entry point that fronts P3's provisioner
 * (GET /api/platform/blueprints + POST /api/platform/provision). No wizard steps,
 * no redeploy: pick a blueprint, name it, provision, open it.
 */
export function NewProjectWizard({
  onClose, onCreated,
}: {
  onClose: () => void;
  onCreated: (useCaseId: string, name: string) => void;
}) {
  const [blueprints, setBlueprints] = useState<Blueprint[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiCall<{ blueprints: Blueprint[] }>("/api/platform/blueprints")
      .then((r) => setBlueprints(r.blueprints || []))
      .catch((e) => setErr(String(e)));
  }, []);

  function slugify(s: string): string {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  }

  async function provision() {
    if (!selected) { setErr("Pick a blueprint to start from."); return; }
    setBusy(true); setErr(null);
    try {
      const bp = blueprints.find((b) => b.id === selected);
      const trimmed = name.trim();
      // A named project gets its own use_case_id; unnamed uses the blueprint id.
      const useCaseId = trimmed ? slugify(trimmed) : selected;
      const res = await apiCall<ProvisionResult>("/api/platform/provision", {
        method: "POST",
        body: JSON.stringify({
          blueprint_id: selected, use_case_id: useCaseId,
          name: trimmed || bp?.name || selected,
        }),
      });
      if (!res.ok) {
        const failed = (res.steps || []).filter((s) => s.status === "error");
        setErr(res.error || `Provisioning failed: ${failed.map((s) => `${s.step} (${s.error})`).join("; ")}`);
        setBusy(false);
        return;
      }
      onCreated(res.use_case_id, res.name);
    } catch (e) {
      setErr(String(e)); setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-gray-100 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">New Project</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Start from a blueprint — it provisions the schema, document types, skills,
              and a starter workflow for you. No setup wizard, no redeploy.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {err && (
            <div className="text-xs bg-red-50 text-red-700 rounded-lg px-3 py-2 border border-red-100">{err}</div>
          )}

          <div className="space-y-2">
            {blueprints.length === 0 && !err && (
              <div className="text-sm text-gray-400">Loading blueprints…</div>
            )}
            {blueprints.map((b) => (
              <button
                key={b.id}
                onClick={() => setSelected(b.id)}
                disabled={busy}
                className={`w-full text-left rounded-xl border-2 p-4 transition-all
                  ${selected === b.id
                    ? "border-blue-500 bg-blue-50/40 ring-1 ring-blue-200"
                    : "border-gray-200 hover:border-blue-300"}`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-4 h-4 rounded-full border-2 flex-shrink-0
                    ${selected === b.id ? "border-blue-500 bg-blue-500" : "border-gray-300"}`} />
                  <span className="text-sm font-bold text-gray-900">{b.name}</span>
                </div>
                {b.description && (
                  <p className="text-xs text-gray-500 mt-1.5 leading-relaxed ml-6">{b.description}</p>
                )}
              </button>
            ))}
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">
              Project name <span className="font-normal text-gray-400">(optional — defaults to the blueprint)</span>
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              placeholder="e.g. Q3 Supplier Review"
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-2">
          <button onClick={onClose} disabled={busy}
            className="text-sm font-medium text-gray-500 hover:text-gray-800 px-4 py-2">Cancel</button>
          <button onClick={provision} disabled={busy || !selected}
            className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded-lg flex items-center gap-2">
            {busy && <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />}
            {busy ? "Provisioning…" : "Create Project"}
          </button>
        </div>
      </div>
    </div>
  );
}
