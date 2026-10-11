"use client";

/**
 * PipelineRunContext
 *
 * Holds the currently-tracked pipeline run and polls its status independently
 * of any tab. Mounted once at the app shell (see app/page.tsx) so the run keeps
 * updating even when the user navigates between workspace tabs. The visual is
 * rendered by <PipelineStatusPopup/>.
 */

import {
  createContext, useContext, useEffect, useRef, useState, useCallback, ReactNode,
} from "react";

export type PipelineTask = { task_key: string; label: string; status: string };

export type PipelineRunState = {
  domainId: string;
  jobName?: string;
  runId?: number;
  runUrl?: string;
  triggeredAt: string;
  status: string;              // running | succeeded | failed | error | skipped | ...
  tasks: PipelineTask[];
  startTimeMs?: number;
  durationMs?: number;
  minimized: boolean;
};

type StartArgs = {
  domainId: string;
  jobName?: string;
  runId?: number;
  runUrl?: string;
};

type Ctx = {
  activeRun: PipelineRunState | null;
  startRun: (a: StartArgs) => void;
  setMinimized: (m: boolean) => void;
  dismiss: () => void;
};

const PipelineRunCtx = createContext<Ctx | null>(null);

export function usePipelineRun(): Ctx {
  const c = useContext(PipelineRunCtx);
  if (!c) throw new Error("usePipelineRun must be used within a PipelineRunProvider");
  return c;
}

const TERMINAL = new Set(["succeeded", "failed", "error", "cancelled", "canceled", "timedout", "skipped"]);

export function PipelineRunProvider({ children }: { children: ReactNode }) {
  const [activeRun, setActiveRun] = useState<PipelineRunState | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAtRef = useRef<number>(0);
  const runRef = useRef<PipelineRunState | null>(null);
  runRef.current = activeRun;

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; }
  }, []);

  // Returns true while polling should continue (false once the run is terminal).
  const poll = useCallback(async (): Promise<boolean> => {
    const cur = runRef.current;
    if (!cur) return false;
    try {
      const r = await fetch(`/api/docintel/pipeline-status?domain_id=${encodeURIComponent(cur.domainId)}`);
      if (!r.ok) return true;
      const d = await r.json();
      setActiveRun(prev => prev ? {
        ...prev,
        status:      d.status || prev.status,
        tasks:       (Array.isArray(d.tasks) && d.tasks.length) ? d.tasks : prev.tasks,
        runUrl:      d.run_url ?? prev.runUrl,
        runId:       d.run_id ?? prev.runId,
        startTimeMs: d.start_time_ms ?? prev.startTimeMs,
        durationMs:  d.duration_ms ?? prev.durationMs,
      } : prev);
      if (TERMINAL.has(String(d.status || "").toLowerCase())) { stopPoll(); return false; }
    } catch { /* silent */ }
    return true;
  }, [stopPoll]);

  // Self-scheduling poll with backoff: batch jobs run for many minutes, so there's
  // no value in a flat 10s cadence. Poll every 5s for the first 30s (catch fast
  // failures), then 15s, then 60s once the job is clearly long-running.
  const scheduleNext = useCallback(() => {
    const elapsed = Date.now() - startedAtRef.current;
    const delay = elapsed > 300_000 ? 60_000 : elapsed > 30_000 ? 15_000 : 5_000;
    pollRef.current = setTimeout(async () => {
      if (await poll()) scheduleNext();
    }, delay);
  }, [poll]);

  const startRun = useCallback((a: StartArgs) => {
    stopPoll();
    setActiveRun({
      domainId: a.domainId,
      jobName:  a.jobName,
      runId:    a.runId,
      runUrl:   a.runUrl,
      triggeredAt: new Date().toLocaleString("en-US", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
      }),
      status: "running",
      tasks: [],
      minimized: false,
    });
    // Brief delay so the run registers before the first poll, then poll on a backoff schedule.
    startedAtRef.current = Date.now();
    setTimeout(() => { void poll(); }, 1500);
    scheduleNext();
  }, [poll, stopPoll, scheduleNext]);

  const setMinimized = useCallback((m: boolean) => {
    setActiveRun(prev => prev ? { ...prev, minimized: m } : prev);
  }, []);

  const dismiss = useCallback(() => { stopPoll(); setActiveRun(null); }, [stopPoll]);

  useEffect(() => () => stopPoll(), [stopPoll]);

  return (
    <PipelineRunCtx.Provider value={{ activeRun, startRun, setMinimized, dismiss }}>
      {children}
    </PipelineRunCtx.Provider>
  );
}
