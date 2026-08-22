"use client";

import { useState } from "react";

/**
 * Human-readable formatter for skill outputs. Doc-reading skills return a small
 * set of well-known shapes (doc_type/confidence, entities[], dates[], summary,
 * changes[]…); render those nicely and fall back to pretty JSON for the rest.
 */
export function FormattedOutputs({ skill, outputs }: {
  skill?: string;
  outputs?: Record<string, unknown> | null;
}) {
  const [raw, setRaw] = useState(false);
  if (!outputs || Object.keys(outputs).length === 0) {
    return <p className="text-xs text-gray-400 mt-1">No output.</p>;
  }

  const chips = (items: string[]) => (
    <span className="flex flex-wrap gap-1 mt-0.5">
      {items.map((c, i) => (
        <span key={i} className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{c}</span>
      ))}
    </span>
  );

  const blocks: React.ReactNode[] = [];

  // classification: doc_type + confidence
  if (typeof outputs.doc_type === "string") {
    const conf = typeof outputs.confidence === "number" ? ` (${Math.round(outputs.confidence * 100)}%)` : "";
    blocks.push(
      <Field key="doc_type" label="Classified as">
        <span className="font-medium text-gray-800">{String(outputs.doc_type)}</span>
        <span className="text-gray-400">{conf}</span>
      </Field>
    );
  }
  // summary
  if (typeof outputs.summary === "string" && outputs.summary.trim()) {
    blocks.push(<Field key="summary" label="Summary"><span className="text-gray-700">{outputs.summary}</span></Field>);
  }
  // entities: [{name,type}]
  if (Array.isArray(outputs.entities)) {
    const ents = outputs.entities as { name?: string; type?: string }[];
    blocks.push(
      <Field key="entities" label={`Entities (${ents.length})`}>
        {chips(ents.map((e) => `${e.name ?? ""}${e.type ? ` · ${e.type}` : ""}`))}
      </Field>
    );
  }
  // dates: [{date,role,label}]
  if (Array.isArray(outputs.dates)) {
    const dates = outputs.dates as { date?: string; role?: string; label?: string }[];
    blocks.push(
      <Field key="dates" label={`Dates (${dates.length})`}>
        <ul className="mt-0.5 space-y-0.5">
          {dates.map((d, i) => (
            <li key={i} className="text-gray-700">
              <span className="font-mono">{d.date}</span>
              {d.label ? ` — ${d.label}` : ""}{d.role && d.role !== "other" ? ` (${d.role})` : ""}
            </li>
          ))}
        </ul>
      </Field>
    );
  }
  // requirements / assessments / gaps / changes / proposed_actions: arrays of objects or strings
  for (const key of ["requirements", "assessments", "gaps", "changes", "proposed_actions", "findings", "events"]) {
    if (Array.isArray(outputs[key])) {
      const arr = outputs[key] as unknown[];
      blocks.push(
        <Field key={key} label={`${cap(key)} (${arr.length})`}>
          <ul className="mt-0.5 space-y-0.5">
            {arr.slice(0, 12).map((it, i) => (
              <li key={i} className="text-gray-700">• {summarizeItem(it)}</li>
            ))}
            {arr.length > 12 && <li className="text-gray-400">…and {arr.length - 12} more</li>}
          </ul>
        </Field>
      );
    }
  }
  // simple scalar fields we haven't already shown
  for (const [k, v] of Object.entries(outputs)) {
    if (["doc_type", "confidence", "summary", "entities", "dates", "evidence",
         "requirements", "assessments", "gaps", "changes", "proposed_actions",
         "findings", "events"].includes(k)) continue;
    if (v == null) continue;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      blocks.push(<Field key={k} label={cap(k)}><span className="text-gray-700">{String(v)}</span></Field>);
    }
  }

  return (
    <div className="mt-1">
      {!raw && blocks.length > 0 ? <div className="space-y-1">{blocks}</div>
        : <pre className="text-xs bg-gray-50 rounded p-2 overflow-x-auto">{JSON.stringify(outputs, null, 2)}</pre>}
      <button onClick={() => setRaw((v) => !v)} className="mt-1 text-[10px] text-gray-400 hover:text-gray-600">
        {raw ? "▸ formatted view" : "▸ raw JSON"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="text-xs">
      <span className="font-semibold text-gray-500">{label}: </span>
      {children}
    </div>
  );
}

function cap(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function summarizeItem(it: unknown): string {
  if (it == null) return "—";
  if (typeof it === "string" || typeof it === "number") return String(it);
  if (typeof it === "object") {
    const o = it as Record<string, unknown>;
    const primary = o.description ?? o.name ?? o.title ?? o.requirement ?? o.text ?? o.change ?? o.finding;
    if (primary) return String(primary);
    return Object.entries(o).slice(0, 3).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
  }
  return String(it);
}
