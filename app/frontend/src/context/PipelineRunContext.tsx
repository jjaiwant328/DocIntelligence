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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runRef = useRef<PipelineRunState | null>(null);
  runRef.current = activeRun;

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const poll = useCallback(async () => {
    const cur = runRef.current;
    if (!cur) return;
    try {
      const r = await fetch(`/api/docintel/pipeline-status?domain_id=${encodeURIComponent(cur.domainId)}`);
      if (!r.ok) return;
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
      if (TERMINAL.has(String(d.status || "").toLowerCase())) stopPoll();
    } catch { /* silent */ }
  }, [stopPoll]);

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
    // Brief delay so the run registers before the first poll, then poll on an interval.
    setTimeout(() => { void poll(); }, 1500);
    pollRef.current = setInterval(() => { void poll(); }, 10000);
  }, [poll, stopPoll]);

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
