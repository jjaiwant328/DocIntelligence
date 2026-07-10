"use client";

/**
 * PipelineStatusPopup
 *
 * Fixed-position status card (bottom-right) that reflects the active pipeline run
 * from PipelineRunContext. Persists across workspace-tab navigation, can be
 * minimized to a pill, and dismissed when the user is done. Live progress polling
 * happens in the provider, so this component simply renders whatever the context holds.
 */

import { usePipelineRun } from "@/context/PipelineRunContext";

const STAGE_STYLE: Record<string, { dot: string; text: string }> = {
  succeeded: { dot: "bg-green-500",               text: "text-green-700" },
  running:   { dot: "bg-blue-500 animate-pulse",  text: "text-blue-700"  },
  failed:    { dot: "bg-red-500",                 text: "text-red-700"   },
  skipped:   { dot: "bg-gray-300",                text: "text-gray-400"  },
  unknown:   { dot: "bg-gray-300",                text: "text-gray-400"  },
};

function fmtDur(ms?: number): string {
  if (!ms) return "";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function PipelineStatusPopup() {
  const { activeRun, setMinimized, dismiss } = usePipelineRun();
  if (!activeRun) return null;

  const st = String(activeRun.status || "").toLowerCase();
  const running = st === "running";
  const isFail = st === "failed" || st === "error";
  const headerColor = st === "succeeded" ? "bg-green-600" : isFail ? "bg-red-600" : "bg-blue-600";
  const icon = running ? "⟳" : st === "succeeded" ? "✓" : isFail ? "✕" : "•";

  if (activeRun.minimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        className={`fixed bottom-4 right-4 z-50 ${headerColor} text-white rounded-full shadow-lg px-4 py-2 text-sm flex items-center gap-2 hover:opacity-90`}
      >
        <span className={running ? "animate-spin inline-block" : ""}>{icon}</span>
        Pipeline: {activeRun.status}
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden">
      <div className={`${headerColor} text-white px-4 py-2 flex items-center justify-between`}>
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span className={running ? "animate-spin inline-block" : ""}>{icon}</span>
          Pipeline {activeRun.status}
        </div>
        <div className="flex items-center gap-1 text-white/90">
          <button onClick={() => setMinimized(true)} title="Minimize"
                  className="hover:bg-white/20 rounded w-6 h-6 leading-none">–</button>
          <button onClick={dismiss} title="Dismiss"
                  className="hover:bg-white/20 rounded w-6 h-6 leading-none">×</button>
        </div>
      </div>

      <div className="px-4 py-3">
        <div className="text-[11px] text-gray-500 mb-2 flex flex-wrap gap-x-3 gap-y-0.5">
          <span>Domain: <span className="font-mono text-gray-700">{activeRun.domainId}</span></span>
          {activeRun.jobName && <span>Job: <span className="font-mono text-gray-700">{activeRun.jobName}</span></span>}
          {activeRun.runId ? <span>Run #{activeRun.runId}</span> : null}
          {activeRun.durationMs ? <span>{fmtDur(activeRun.durationMs)}</span> : null}
        </div>

        {activeRun.tasks.length === 0 ? (
          <div className="text-xs text-gray-400 py-2 flex items-center gap-2">
            <span className="animate-spin inline-block">⟳</span> Starting pipeline…
          </div>
        ) : (
          <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {activeRun.tasks.map(t => {
              const s = STAGE_STYLE[String(t.status || "unknown").toLowerCase()] || STAGE_STYLE.unknown;
              return (
                <div key={t.task_key} className="flex items-center gap-2 text-xs">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
                  <span className={`flex-1 truncate ${s.text}`}>{t.label || t.task_key}</span>
                  <span className="text-gray-400 shrink-0">{t.status}</span>
                </div>
              );
            })}
          </div>
        )}

        {activeRun.runUrl && (
          <a href={activeRun.runUrl} target="_blank" rel="noreferrer"
             className="mt-2 inline-block text-[11px] text-blue-600 hover:underline">
            Open run in Databricks ↗
          </a>
        )}
      </div>
    </div>
  );
}
