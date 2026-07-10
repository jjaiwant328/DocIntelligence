"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getApiBaseUrl } from "@/lib/api-config";
import { useDomain } from "@/context/DomainContext";
import { DocViewerPanel } from "@/components/DocViewerPanel";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Restaurant   { restaurant_name: string; state: string; region: string; quantity_cases: number; estimated_revenue_usd: number; delivery_date: string; }
interface Financial    { component: string; amount_usd: number; source: string; }
interface RecallData   { lot_number: string; impacted_restaurants: Restaurant[]; restaurant_count: number; financial_breakdown: Financial[]; total_gross_usd: number; total_net_usd: number; }
interface Supplier     { supplier_name: string; supplier_id: string; region: string; risk_score: number; risk_category: string; }
interface TimelineEvent{ event_time: string; event: string; detail: string; severity: "info"|"warning"|"critical"; }
interface TimelineData { shipment_id: string; timeline: TimelineEvent[]; }
interface OntNode      { id: string; label: string; type: string; x: number; y: number; risk: string; }
interface OntEdge      { source: string; target: string; label: string; }
interface OntGraph     { nodes: OntNode[]; edges: OntEdge[]; source: string; }
interface ActionEntry  { action_id: string; logged_at: string; action_type: string; description: string; priority: string; incident_ref: string; logged_by: string; status: string; }

// Generic domain overview (non-supply-chain)
interface DocTypeRow      { doc_type: string; doc_count: number; }
interface EntityTypeRow   { entity_type: string; count: number; }
interface ExtractionRow   { doc_id: string; doc_type: string; field_name: string; field_value: string; }
interface RecentIncident  { incident_id: string; incident_type: string; title: string; status: string; severity: string; opened_date: string; }
interface DomainOverview  {
  domain_id: string;
  total_docs: number;
  doc_types: DocTypeRow[];
  total_entities: number;
  entity_types: EntityTypeRow[];
  total_relationships: number;
  recent_extractions: ExtractionRow[];
  total_incidents: number;
  incident_counts: Record<string,number>;
  recent_incidents: RecentIncident[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function fetchJson(path: string) {
  const base = getApiBaseUrl();
  const r = await fetch(`${base}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function postJson(path: string, body: object) {
  const base = getApiBaseUrl();
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function fmt(n: number) { return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0 })}`; }
function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const sevBg:  Record<string,string> = { info:"bg-blue-50 border-blue-200 text-blue-800", warning:"bg-amber-50 border-amber-200 text-amber-800", critical:"bg-red-50 border-red-200 text-red-800" };
const sevDot: Record<string,string> = { info:"bg-blue-400", warning:"bg-amber-400", critical:"bg-red-500" };
const prioColor: Record<string,string> = { CRITICAL:"text-red-700 bg-red-50 border border-red-200", HIGH:"text-orange-700 bg-orange-50 border border-orange-200", MEDIUM:"text-amber-700 bg-amber-50 border border-amber-200", LOW:"text-gray-600 bg-gray-50 border border-gray-200" };
const nodeColor: Record<string,string> = {
  Supplier:            "#2563eb",  // bold blue
  Carrier:             "#7c3aed",  // purple
  Lot:                 "#dc2626",  // red
  Shipment:            "#0891b2",  // cyan
  Equipment:           "#d97706",  // amber
  QualityIncident:     "#db2777",  // hot pink
  RecallEvent:         "#991b1b",  // dark crimson (distinct from Lot red)
  DistributionCenter:  "#059669",  // emerald green
  RestaurantGroup:     "#ea580c",  // orange
  Document:            "#6d28d9",  // violet
  Product:             "#0284c7",  // sky blue
  Contract:            "#374151",  // dark slate
  Restaurant:          "#b45309",  // brown/tan
  TemperatureExcursion:"#be185d",  // rose
  default:             "#64748b",
};

// ── Action Playbooks ──────────────────────────────────────────────────────────

interface Playbook {
  id: string; category: string; name: string; description: string;
  priority: "CRITICAL"|"HIGH"|"MEDIUM"|"LOW";
  action_type: string; what_it_does: string;
  next_steps: string[]; default_logged_by: string;
  source_doc_types?: string[];   // doc types in the Library relevant to this action
}

// Slim doc reference used in Action Center
interface ActionDocRef {
  doc_id: string;
  filename: string;
  doc_type: string;
  processed_ts?: string;
}

// Supply Chain playbooks
const SC_PLAYBOOKS: Playbook[] = [
  { id:"rcl-notify",   category:"Recall",         priority:"CRITICAL", action_type:"RECALL_NOTIFICATION",
    name:"Notify Affected Restaurants",
    description:"Send immediate quarantine instructions to all affected locations that received the recalled lot.",
    what_it_does:"Triggers outreach to restaurant managers and ops team to quarantine recalled product, stop service, and initiate return logistics.",
    next_steps:["Confirm receipt from all managers within 2 hours","Track product retrieval per location","Document compliance and chain of custody"],
    default_logged_by:"Recall Coordinator",
    source_doc_types:["recall_notice","distribution_record","restaurant_list"] },
  { id:"rcl-fda",      category:"Recall",         priority:"CRITICAL", action_type:"REGULATORY_FILING",
    name:"File FDA Voluntary Recall Report",
    description:"Submit Class II voluntary recall notification to FDA CFSAN under 21 CFR Part 7 for the affected lot.",
    what_it_does:"Generates FDA recall report including product identification, distribution scope, health hazard assessment, and corrective actions.",
    next_steps:["Await FDA acknowledgment (72 hours)","Prepare public-facing recall notice","Update recall status database"],
    default_logged_by:"Regulatory Affairs",
    source_doc_types:["recall_notice","lab_report","regulatory_filing"] },
  { id:"rcl-destroy",  category:"Recall",         priority:"HIGH",     action_type:"PRODUCT_HOLD",
    name:"Authorize Product Destruction",
    description:"Authorize certified destruction of recovered product cases at approved facility.",
    what_it_does:"Issues destruction order, generates chain of custody documentation, and schedules certified waste transport.",
    next_steps:["Obtain destruction certificate","Update financial claim with disposal costs","Close lot tracking in WMS"],
    default_logged_by:"QA Manager",
    source_doc_types:["product_hold_order","distribution_record","lab_report"] },
  { id:"sup-penalty",  category:"Supplier",       priority:"HIGH",     action_type:"FINANCIAL_CLAIM",
    name:"Issue Supplier Penalty Notice",
    description:"Issue penalty notice per supplier contract terms for SLA or quality violation.",
    what_it_does:"Generates formal penalty notice referencing contract clause, violation evidence, and cost breakdown.",
    next_steps:["Supplier acknowledgment within 5 business days","Track invoice payment","Record in supplier scorecard"],
    default_logged_by:"Supplier Quality",
    source_doc_types:["supplier_contract","quality_report","purchase_order"] },
  { id:"sup-audit",    category:"Supplier",       priority:"HIGH",     action_type:"CORRECTIVE_ACTION",
    name:"Schedule Emergency Supplier Audit",
    description:"Schedule unannounced audit of supplier facility within 30 days.",
    what_it_does:"Assigns cross-functional audit team, creates audit checklist, sets corrective action tracking.",
    next_steps:["Confirm audit date with facility","Brief audit team","Prepare corrective action tracking sheet"],
    default_logged_by:"Supplier Quality",
    source_doc_types:["audit_report","supplier_contract","quality_report"] },
  { id:"sup-watch",    category:"Supplier",       priority:"MEDIUM",   action_type:"SUPPLIER_CONTACT",
    name:"Downgrade Supplier Status",
    description:"Temporarily downgrade supplier from ACCEPTABLE to CONDITIONAL status pending corrective action.",
    what_it_does:"Updates supplier scorecard, flags future POs for enhanced QC review, and notifies procurement.",
    next_steps:["Notify procurement team immediately","Implement enhanced receiving inspection","Schedule 90-day status review"],
    default_logged_by:"Procurement Manager",
    source_doc_types:["supplier_contract","quality_report"] },
  { id:"car-claim",    category:"Carrier",        priority:"MEDIUM",   action_type:"FINANCIAL_CLAIM",
    name:"File Carrier Liability Claim",
    description:"Submit cost-share liability claim to carrier per contract SLA terms.",
    what_it_does:"Generates carrier claim document referencing SLA maintenance obligations and cost breakdown.",
    next_steps:["Carrier acknowledgment within 10 business days","Update net financial exposure","Evaluate carrier contract renewal"],
    default_logged_by:"Legal/Finance",
    source_doc_types:["carrier_contract","shipping_record","maintenance_log"] },
  { id:"car-audit",    category:"Carrier",        priority:"MEDIUM",   action_type:"INSPECTION",
    name:"Inspect Carrier Maintenance Records",
    description:"Request full maintenance history for implicated carrier vehicle.",
    what_it_does:"Issues formal records request, logs review in audit trail, schedules vehicle re-certification before next use.",
    next_steps:["Review records within 3 business days","Determine if vehicle is fit for service","Update carrier scorecard"],
    default_logged_by:"Fleet Manager",
    source_doc_types:["maintenance_log","carrier_contract"] },
  { id:"inv-rca",      category:"Investigation",  priority:"HIGH",     action_type:"ROOT_CAUSE_ANALYSIS",
    name:"Open Root Cause Analysis",
    description:"Initiate structured 8D root cause analysis for the triggering failure.",
    what_it_does:"Creates RCA ticket, assigns cross-functional team, sets 10-business-day deadline for 8D report.",
    next_steps:["Assign RCA lead within 24 hours","Gather logs and statements","Complete interim containment by EOD"],
    default_logged_by:"QA Lead",
    source_doc_types:["lab_report","quality_report","incident_report","shipping_record"] },
  { id:"inv-dc",       category:"Investigation",  priority:"MEDIUM",   action_type:"INSPECTION",
    name:"Enhanced Receiving Inspection",
    description:"Implement 100% temperature-probe receiving inspection for at-risk shipments for 90 days.",
    what_it_does:"Updates receiving SOP, trains DC staff on enhanced protocol, configures automatic log capture.",
    next_steps:["Distribute updated SOP to DC staff","Train receiving team","Set 90-day monitoring calendar alert"],
    default_logged_by:"DC Operations Manager",
    source_doc_types:["shipping_record","distribution_record","quality_report"] },
  { id:"fin-insurance",category:"Financial",      priority:"HIGH",     action_type:"FINANCIAL_CLAIM",
    name:"File Product Liability Insurance Claim",
    description:"Submit insurance claim for incident-related costs including disposal and lost revenue.",
    what_it_does:"Compiles claim package: incident report, financial exposure breakdown, destruction certificates, and regulatory filings.",
    next_steps:["Insurer acknowledgment within 5 business days","Provide supporting documentation pack","Track claim number and payment timeline"],
    default_logged_by:"Risk/Finance",
    source_doc_types:["incident_report","regulatory_filing","lab_report"] },
  { id:"fin-credit",   category:"Financial",      priority:"MEDIUM",   action_type:"FINANCIAL_CLAIM",
    name:"Issue Credit Memos to Affected Locations",
    description:"Issue credit memos to affected locations for recalled product revenue loss.",
    what_it_does:"Generates per-location credit calculations based on quantity, average selling price, and days impacted.",
    next_steps:["Calculate per-location credit amounts","Finance approves credit memos","Distribute to accounting"],
    default_logged_by:"Finance",
    source_doc_types:["distribution_record","restaurant_list","recall_notice"] },
  { id:"com-ops",      category:"Communication",  priority:"CRITICAL", action_type:"DISTRIBUTION_CENTER_ALERT",
    name:"Alert Operations Team",
    description:"Send priority alert to operations about active incident requiring immediate action.",
    what_it_does:"Sends SMS and email via ops notification system with incident details, quarantine instructions, and escalation contacts.",
    next_steps:["Confirm all managers received alert","Schedule ops bridge call","Track compliance by location"],
    default_logged_by:"Operations Director",
    source_doc_types:["recall_notice","incident_report","distribution_record"] },
  { id:"com-exec",     category:"Communication",  priority:"HIGH",     action_type:"MEDIA_STATEMENT",
    name:"Executive Leadership Briefing",
    description:"Prepare and deliver executive briefing on incident scope, financial impact, root cause, and corrective action plan.",
    what_it_does:"Generates executive summary with KPI dashboard, incident timeline, financial breakdown, and recommended decisions.",
    next_steps:["Schedule briefing within 24 hours","Prepare decision brief and Q&A","Document executive decisions in action log"],
    default_logged_by:"VP Supply Chain",
    source_doc_types:["incident_report","recall_notice","lab_report","regulatory_filing"] },
  { id:"com-health",   category:"Communication",  priority:"HIGH",     action_type:"REGULATORY_FILING",
    name:"Notify State / Federal Health Authorities",
    description:"Notify relevant state and federal health departments about the incident.",
    what_it_does:"Files regulatory notices, provides distribution list and health hazard assessment.",
    next_steps:["File notifications within 48 hours","Coordinate with FDA on messaging","Document all contacts"],
    default_logged_by:"Regulatory Affairs",
    source_doc_types:["regulatory_filing","recall_notice","lab_report"] },
];

// Compliance playbooks
const COMPLIANCE_PLAYBOOKS: Playbook[] = [
  { id:"cmp-notice",   category:"Violation",      priority:"CRITICAL", action_type:"REGULATORY_FILING",
    name:"Issue Violation Notice Response",
    description:"Draft and submit formal response to regulatory violation notice within the specified deadline.",
    what_it_does:"Creates written response package: admission or dispute of findings, corrective action plan, and timeline commitments.",
    next_steps:["Legal review within 24 hours","Submit response by deadline","Track regulator acknowledgment"],
    default_logged_by:"Regulatory Affairs",
    source_doc_types:["violation_notice","regulatory_correspondence","inspection_report"] },
  { id:"cmp-cap",      category:"Violation",      priority:"HIGH",     action_type:"CORRECTIVE_ACTION",
    name:"Open Corrective Action Plan (CAP)",
    description:"Initiate a structured corrective action plan for open violation or inspection finding.",
    what_it_does:"Creates CAP ticket, assigns responsible owner, sets completion deadline, and links to source document.",
    next_steps:["Assign CAP owner within 24 hours","Define measurable completion criteria","Schedule 30-day check-in"],
    default_logged_by:"Compliance Manager",
    source_doc_types:["violation_notice","inspection_report","corrective_action_plan"] },
  { id:"cmp-permit",   category:"Permit",         priority:"HIGH",     action_type:"REGULATORY_FILING",
    name:"Initiate Permit Renewal",
    description:"Begin permit or license renewal process before expiration date identified in documents.",
    what_it_does:"Compiles renewal application, gathers supporting documentation, and submits to issuing authority.",
    next_steps:["Gather required supporting documents","Submit application 60 days before expiration","Track application status"],
    default_logged_by:"Compliance Officer",
    source_doc_types:["permit","license","regulatory_correspondence"] },
  { id:"cmp-permit-alert", category:"Permit",     priority:"MEDIUM",   action_type:"CORRECTIVE_ACTION",
    name:"Set Permit Expiration Alert",
    description:"Register upcoming permit expiration for automated tracking and reminders.",
    what_it_does:"Creates calendar alert, assigns renewal owner, and links to permit document in system.",
    next_steps:["Confirm expiration date from document","Assign renewal owner","Schedule 90-day and 30-day reminders"],
    default_logged_by:"Compliance Coordinator",
    source_doc_types:["permit","license"] },
  { id:"cmp-inspect",  category:"Inspection",     priority:"HIGH",     action_type:"INSPECTION",
    name:"Respond to Inspection Finding",
    description:"Prepare and submit formal response to inspection finding or deficiency notice.",
    what_it_does:"Reviews inspection report, classifies findings by severity, drafts response letter with corrective timelines.",
    next_steps:["Classify finding severity within 24 hours","Draft response letter","Assign field team for remediation"],
    default_logged_by:"District Manager",
    source_doc_types:["inspection_report","deficiency_notice","regulatory_correspondence"] },
  { id:"cmp-inspect-prep", category:"Inspection", priority:"MEDIUM",   action_type:"INSPECTION",
    name:"Pre-Inspection Readiness Check",
    description:"Conduct internal readiness review before scheduled or anticipated inspection.",
    what_it_does:"Runs internal checklist against current regulations, identifies gaps, and assigns remediation tasks.",
    next_steps:["Distribute checklist to location managers","Complete gap remediation","Document readiness status"],
    default_logged_by:"Compliance Team",
    source_doc_types:["inspection_report","policy_document","corrective_action_plan"] },
  { id:"cmp-training", category:"Training",       priority:"HIGH",     action_type:"CORRECTIVE_ACTION",
    name:"Schedule Compliance Training",
    description:"Schedule required regulatory or safety training for staff with expiring certifications.",
    what_it_does:"Enrolls staff in required training program, tracks completion, and updates certification records.",
    next_steps:["Identify staff requiring training","Schedule training session","Record completions in HR system"],
    default_logged_by:"HR / Training Lead",
    source_doc_types:["training_record","certification","policy_document"] },
  { id:"cmp-cert",     category:"Training",       priority:"MEDIUM",   action_type:"CORRECTIVE_ACTION",
    name:"Renew Staff Certifications",
    description:"Process renewal of professional certifications expiring within 90 days per document review.",
    what_it_does:"Compiles list of expiring certifications from parsed documents, contacts staff, and tracks renewal status.",
    next_steps:["List expiring certifications","Contact staff 60 days before expiry","Update certification records"],
    default_logged_by:"Compliance Coordinator",
    source_doc_types:["certification","training_record"] },
  { id:"cmp-vendor",   category:"Vendor",         priority:"HIGH",     action_type:"INSPECTION",
    name:"Audit Vendor Compliance Certifications",
    description:"Request and verify up-to-date compliance certifications from vendors identified in parsed documents.",
    what_it_does:"Issues certification request letters, tracks responses, and flags overdue vendors.",
    next_steps:["Send certification request to vendor","Set 10-day response deadline","Escalate non-responsive vendors"],
    default_logged_by:"Vendor Management",
    source_doc_types:["vendor_agreement","certification","audit_report"] },
  { id:"cmp-vendor-cap", category:"Vendor",       priority:"MEDIUM",   action_type:"CORRECTIVE_ACTION",
    name:"Issue Vendor Corrective Action",
    description:"Issue formal corrective action request to non-compliant vendor.",
    what_it_does:"Generates vendor CAP letter referencing specific compliance gaps and required remediation.",
    next_steps:["Send CAP to vendor","Track vendor response","Schedule follow-up audit"],
    default_logged_by:"Procurement / Compliance",
    source_doc_types:["vendor_agreement","audit_report","corrective_action_plan"] },
  { id:"cmp-filing",   category:"Filing",         priority:"CRITICAL", action_type:"REGULATORY_FILING",
    name:"Submit Regulatory Report",
    description:"Prepare and submit required regulatory report or filing identified in compliance documents.",
    what_it_does:"Compiles required data, generates report in prescribed format, and submits to regulatory body.",
    next_steps:["Confirm filing deadline","Assemble required data","Submit and retain confirmation receipt"],
    default_logged_by:"Regulatory Affairs",
    source_doc_types:["regulatory_correspondence","policy_document","inspection_report"] },
  { id:"cmp-filing-response", category:"Filing",  priority:"HIGH",     action_type:"REGULATORY_FILING",
    name:"Respond to Regulatory Inquiry",
    description:"Draft and submit response to formal regulatory inquiry or information request.",
    what_it_does:"Coordinates with legal and operations to compile response package within required timeframe.",
    next_steps:["Assign response lead within 24 hours","Compile requested information","Legal review before submission"],
    default_logged_by:"Regulatory Affairs / Legal",
    source_doc_types:["regulatory_correspondence","violation_notice","policy_document"] },
];

// Generic playbooks for any other domain
const DEFAULT_PLAYBOOKS: Playbook[] = [
  { id:"dflt-review",  category:"Review",         priority:"HIGH",     action_type:"ROOT_CAUSE_ANALYSIS",
    name:"Initiate Document Review",
    description:"Assign a cross-functional review of key documents and extract open action items.",
    what_it_does:"Creates review ticket, assigns document owners, sets 10-day deadline for findings report.",
    next_steps:["Assign review lead","Distribute documents to reviewers","Compile findings report"],
    default_logged_by:"Team Lead",
    source_doc_types:[] },
  { id:"dflt-action",  category:"Action",         priority:"HIGH",     action_type:"CORRECTIVE_ACTION",
    name:"Open Corrective Action",
    description:"Create a corrective action item for a finding identified in the document library.",
    what_it_does:"Logs corrective action with owner, deadline, and linked document evidence.",
    next_steps:["Assign CAP owner","Define completion criteria","Schedule check-in"],
    default_logged_by:"Manager",
    source_doc_types:[] },
  { id:"dflt-comm",    category:"Communication",  priority:"MEDIUM",   action_type:"MEDIA_STATEMENT",
    name:"Notify Stakeholders",
    description:"Send stakeholder communication about key findings or required actions.",
    what_it_does:"Generates notification based on document findings and delivers to relevant stakeholders.",
    next_steps:["Draft notification","Route for approval","Send and track acknowledgment"],
    default_logged_by:"Communications Lead",
    source_doc_types:[] },
  { id:"dflt-filing",  category:"Filing",         priority:"HIGH",     action_type:"REGULATORY_FILING",
    name:"Submit Required Filing",
    description:"Submit a required report or filing based on document review findings.",
    what_it_does:"Compiles required data from documents and submits to relevant authority.",
    next_steps:["Confirm filing deadline","Assemble data","Submit and retain receipt"],
    default_logged_by:"Compliance Team",
    source_doc_types:[] },
];

// Domain-specific category sets
const CATEGORIES_BY_DOMAIN: Record<string, string[]> = {
  supply_chain: ["All", "Recall", "Supplier", "Carrier", "Investigation", "Financial", "Communication"],
  compliance:   ["All", "Violation", "Permit", "Inspection", "Training", "Vendor", "Filing"],
};
const DEFAULT_CATEGORIES = ["All", "Action", "Review", "Communication", "Filing", "Investigation"];

function getDomainPlaybooks(domainId: string): Playbook[] {
  if (domainId === "supply_chain") return SC_PLAYBOOKS;
  if (domainId === "compliance")   return COMPLIANCE_PLAYBOOKS;
  return DEFAULT_PLAYBOOKS;
}
function getDomainCategories(domainId: string): string[] {
  return CATEGORIES_BY_DOMAIN[domainId] ?? DEFAULT_CATEGORIES;
}

// Shared colour maps (works for both SC and compliance categories)
const CAT_COLOR: Record<string,string> = {
  // Supply chain
  Recall:"bg-red-100 text-red-800 border-red-200",
  Supplier:"bg-orange-100 text-orange-800 border-orange-200",
  Carrier:"bg-amber-100 text-amber-800 border-amber-200",
  // Compliance
  Violation:"bg-red-100 text-red-800 border-red-200",
  Permit:"bg-sky-100 text-sky-800 border-sky-200",
  Inspection:"bg-violet-100 text-violet-800 border-violet-200",
  Training:"bg-emerald-100 text-emerald-800 border-emerald-200",
  Vendor:"bg-orange-100 text-orange-800 border-orange-200",
  Filing:"bg-blue-100 text-blue-800 border-blue-200",
  // Shared
  Investigation:"bg-purple-100 text-purple-800 border-purple-200",
  Financial:"bg-blue-100 text-blue-800 border-blue-200",
  Communication:"bg-teal-100 text-teal-800 border-teal-200",
  Action:"bg-indigo-100 text-indigo-800 border-indigo-200",
  Review:"bg-gray-100 text-gray-800 border-gray-200",
};
const CAT_DOT: Record<string,string> = {
  Recall:"bg-red-500", Supplier:"bg-orange-500", Carrier:"bg-amber-500",
  Violation:"bg-red-500", Permit:"bg-sky-500", Inspection:"bg-violet-500",
  Training:"bg-emerald-500", Vendor:"bg-orange-500", Filing:"bg-blue-500",
  Investigation:"bg-purple-500", Financial:"bg-blue-500", Communication:"bg-teal-500",
  Action:"bg-indigo-500", Review:"bg-gray-400",
};

// ── Top-level navigation definition ──────────────────────────────────────────

function buildTabs(domainId: string) {
  const categories = getDomainCategories(domainId);
  return [
    {
      id: "overview",
      icon: "📊",
      label: "Overview",
      tooltip: "Document processing stats, entity distribution, and key extractions",
      subs: [] as { id: string; label: string }[],
    },
    {
      id: "ontology",
      icon: "🕸",
      label: "Knowledge Graph",
      tooltip: "Interactive knowledge graph — entities extracted from documents and their relationships",
      subs: [
        { id:"graph",    label:"Graph View" },
        { id:"entities", label:"Entity List" },
      ],
    },
    {
      id: "actions",
      icon: "⚡",
      label: "Action Center",
      tooltip: "Log actions, track open items, and generate response reports for this subject area",
      subs: [
        ...categories.map(c => ({ id: c.toLowerCase(), label: c })),
        { id: "reports", label: "Action Reports" },
      ],
    },
    {
      id: "compliance_map",
      icon: "🗺",
      label: "Compliance Map",
      tooltip: "Jurisdiction × document-type coverage matrix — see which regulations apply where and identify gaps",
      subs: [
        { id: "map",    label: "Coverage Matrix" },
        { id: "digest", label: "Action Digest" },
        { id: "pulse",  label: "Regulatory Pulse" },
      ],
    },
    {
      id: "copilot",
      icon: "🧠",
      label: "Copilot Studio",
      tooltip: "Paste your guiding instructions, analyze data readiness, and run AI-powered intelligence queries against your documents",
      subs: [
        { id: "setup",     label: "Setup & Readiness" },
        { id: "briefings", label: "Intelligence Briefings" },
        { id: "ask",       label: "Ask Copilot" },
        { id: "legal",     label: "Legal Queue" },
      ],
    },
  ];
}

// ── Structured Copilot Response Renderer ─────────────────────────────────────

interface CopilotSections {
  facts?: string;
  interpretations?: string;
  sources?: string;
  risks?: string;
  open_questions?: string;
  next_steps?: string;
}

interface CopilotResult {
  sections: CopilotSections;
  attorney_review: boolean;
  cited_docs: string[];
  raw_answer: string;
  query: string;
  confidence?: string;    // HIGH | MEDIUM | LOW | UNABLE_TO_VERIFY
  source_tier?: string;   // user_docs | regulatory | inferred
}

function StructuredCopilotResponse({ result, onDocClick }: { result: CopilotResult; onDocClick?: (docId: string) => void }) {
  const sections = result?.sections ?? {};
  const citedDocs = result?.cited_docs ?? [];
  const rawAnswer = result?.raw_answer ?? "";
  const hasStructure = Object.values(sections).some(v => v && v.trim().length > 0);

  if (!hasStructure) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4 text-sm text-gray-700">
        <pre className="whitespace-pre-wrap font-sans">{rawAnswer}</pre>
      </div>
    );
  }

  const sectionDefs = [
    { key: "facts",          label: "Facts",                   icon: "📋", bg: "bg-blue-50",   border: "border-blue-200",   text: "text-blue-800",   head: "text-blue-700" },
    { key: "interpretations",label: "Interpretations",         icon: "🔍", bg: "bg-purple-50", border: "border-purple-200", text: "text-purple-800", head: "text-purple-700" },
    { key: "sources",        label: "Sources",                 icon: "📂", bg: "bg-green-50",  border: "border-green-200",  text: "text-green-800",  head: "text-green-700" },
    { key: "risks",          label: "Risks",                   icon: "⚠️", bg: "bg-red-50",    border: "border-red-200",    text: "text-red-800",    head: "text-red-700" },
    { key: "open_questions", label: "Open Questions",          icon: "❓", bg: "bg-amber-50",  border: "border-amber-200",  text: "text-amber-800",  head: "text-amber-700" },
    { key: "next_steps",     label: "Recommended Next Steps",  icon: "✅", bg: "bg-indigo-50", border: "border-indigo-200", text: "text-indigo-800", head: "text-indigo-700" },
  ] as const;

  const confidenceStyle: Record<string, string> = {
    HIGH: "bg-green-100 text-green-700 border-green-200",
    MEDIUM: "bg-amber-100 text-amber-700 border-amber-200",
    LOW: "bg-red-100 text-red-700 border-red-200",
    UNABLE_TO_VERIFY: "bg-gray-100 text-gray-600 border-gray-200",
  };
  const sourceTierLabel: Record<string, string> = {
    user_docs:  "📑 Grounded in documents",
    regulatory: "🏛 Regulatory sources",
    inferred:   "💡 AI inference — verify independently",
  };

  return (
    <div className="space-y-3">
      {/* Confidence + Source Tier row */}
      {(result?.confidence || result?.source_tier) && (
        <div className="flex items-center gap-2 flex-wrap">
          {result.confidence && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${confidenceStyle[result.confidence] ?? confidenceStyle.LOW}`}>
              Confidence: {result.confidence.replace(/_/g, " ")}
            </span>
          )}
          {result.source_tier && (
            <span className="text-[10px] text-gray-500 font-medium">
              {sourceTierLabel[result.source_tier] ?? result.source_tier}
            </span>
          )}
        </div>
      )}
      {result?.attorney_review && (
        <div className="flex items-center gap-2 bg-red-600 text-white text-xs font-semibold px-4 py-2 rounded-lg">
          <span className="text-base">⚖️</span>
          Attorney Review Recommended — this response contains guidance requiring legal review before action.
        </div>
      )}
      {sectionDefs.map(sec => {
        const content = sections[sec.key as keyof CopilotSections];
        if (!content?.trim()) return null;
        return (
          <div key={sec.key} className={`${sec.bg} ${sec.border} border rounded-lg p-4`}>
            <div className={`flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider ${sec.head} mb-2`}>
              <span>{sec.icon}</span>
              <span>{sec.label}</span>
            </div>
            <div className={`text-sm ${sec.text} whitespace-pre-wrap leading-relaxed`}>
              {content}
            </div>
          </div>
        );
      })}
      {citedDocs.length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wide mb-2">
            📄 Source Documents Referenced
          </p>
          <div className="flex flex-wrap gap-1.5">
            {citedDocs.map((d) => (
              <button
                key={d}
                onClick={() => {
                  if (onDocClick) {
                    onDocClick(d);
                  } else {
                    // Default fallback: navigate to Library with correct JSON payload
                    try { sessionStorage.setItem("docintel_highlight_doc", JSON.stringify({ doc_id: d, domain_id: "supply_chain" })); } catch {}
                    window.location.href = `/document-intelligence?domain_id=supply_chain&step=library`;
                  }
                }}
                title="Click to view this document in the Library"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-[10px] font-medium hover:bg-blue-100 hover:border-blue-400 transition-colors cursor-pointer"
              >
                <span className="font-mono truncate max-w-[160px]">{d.replace(/\.pdf$/i, "")}</span>
                <span className="text-blue-400 text-[9px]">↗</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Copilot Studio ────────────────────────────────────────────────────────────

interface GapReport {
  required: string[];
  available: Record<string, number>;
  covered: Record<string, number>;
  gaps: string[];
  total_docs: number;
  coverage_pct: number;
  ready_to_proceed: boolean;
  message: string;
}

const BRIEFING_QUERIES_BY_DOMAIN: Record<string, string[]> = {
  supply_chain: [
    "Summarize all open recall events and their impact on restaurants. Cite document IDs.",
    "Which suppliers currently have the highest risk scores and what are the root causes?",
    "What shipments or lots have temperature excursions or quality issues pending resolution?",
    "What contract obligations or SLA violations are at risk in the next 30 days?",
  ],
  compliance: [
    "Summarize all compliance correspondence and identify open action items, owners, and deadlines.",
    "What regulatory risks are currently identified across all documents? Cite sources.",
    "Which stores or jurisdictions have the most pending violations or corrective actions?",
    "What compliance requirements have effective dates in the next 90 days?",
  ],
};
const DEFAULT_BRIEFING_QUERIES = [
  "Summarize key findings across all documents and identify open action items.",
  "What risks or issues are currently identified? Cite document sources.",
  "Which entities or locations have the most outstanding items?",
  "What deadlines or expiration dates require attention in the next 90 days?",
];

function getBriefingQueries(domainId: string): string[] {
  return BRIEFING_QUERIES_BY_DOMAIN[domainId] ?? DEFAULT_BRIEFING_QUERIES;
}

// Prompt library types
interface PromptRecord {
  prompt_id: string;
  name: string;
  is_active: boolean;
  preview: string;
  created_at: string;
  created_by: string;
}

function CopilotStudio({ domainId, sub, apiBase, onSwitchToSetup }: {
  domainId: string; sub: string; apiBase: string;
  onSwitchToSetup?: () => void;
}) {
  const [savedPrompt,   setSavedPrompt]   = useState<string | null>(null);
  const [savedAt,       setSavedAt]       = useState<string | null>(null);
  const [draftPrompt,   setDraftPrompt]   = useState("");
  const [draftName,     setDraftName]     = useState("");   // name for new prompt
  const [gapReport,     setGapReport]     = useState<GapReport | null>(null);
  const [analyzing,     setAnalyzing]     = useState(false);
  const [saving,        setSaving]        = useState(false);
  const [editMode,      setEditMode]      = useState(false);

  // Prompt library
  const [promptLibrary,   setPromptLibrary]   = useState<PromptRecord[]>([]);
  const [libraryLoading,  setLibraryLoading]  = useState(false);
  const [editingPromptId, setEditingPromptId] = useState<string | null>(null);
  const [showAddNew,      setShowAddNew]      = useState(false);

  // Briefings state
  const briefingQueries = getBriefingQueries(domainId);
  const [briefings, setBriefings] = useState<(CopilotResult | null | "loading")[]>(
    briefingQueries.map(() => null)
  );

  // Ask state
  const [askQuery,   setAskQuery]   = useState("");
  const [askResult,  setAskResult]  = useState<CopilotResult | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [addToLegal, setAddToLegal] = useState(false);

  // Load prompt library
  const loadPromptLibrary = useCallback(() => {
    setLibraryLoading(true);
    fetch(`${apiBase}/api/docintel/copilot-prompts?domain_id=${domainId}`)
      .then(r => r.ok ? r.json() : { prompts: [], active_prompt_text: null })
      .then(d => {
        setPromptLibrary(d.prompts || []);
        if (d.active_prompt_text) {
          setSavedPrompt(d.active_prompt_text);
        }
      })
      .catch(() => {})
      .finally(() => setLibraryLoading(false));
  }, [domainId, apiBase]);

  // Load saved prompt on mount (legacy + library)
  useEffect(() => {
    fetch(`${apiBase}/api/docintel/copilot-prompt?domain_id=${domainId}`)
      .then(r => r.json())
      .then(d => {
        if (d.prompt) {
          setSavedPrompt(d.prompt);
          setSavedAt(d.saved_at);
        }
      })
      .catch(() => {});
    loadPromptLibrary();
  }, [domainId, apiBase, loadPromptLibrary]);

  // Auto-run briefings when switching to that sub-tab (if prompt is saved)
  useEffect(() => {
    if (sub !== "briefings" || !savedPrompt) return;
    // Only run briefings that haven't been loaded yet
    briefingQueries.forEach((q, i) => {
      if (briefings[i] !== null) return;
      setBriefings(prev => { const n = [...prev]; n[i] = "loading"; return n; });
      fetch(`${apiBase}/api/docintel/copilot-query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, query: q }),
      })
        .then(r => r.json())
        .then(d => setBriefings(prev => { const n = [...prev]; n[i] = d; return n; }))
        .catch(() => setBriefings(prev => { const n = [...prev]; n[i] = null; return n; }));
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub, savedPrompt]);

  const handleAnalyze = async () => {
    if (!draftPrompt.trim()) return;
    setAnalyzing(true);
    setGapReport(null);
    try {
      const res = await fetch(`${apiBase}/api/docintel/copilot-analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, prompt: draftPrompt }),
      });
      setGapReport(await res.json());
    } catch {
      setGapReport(null);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSave = async (skipAnalyze = false) => {
    if (!draftPrompt.trim()) return;
    setSaving(true);
    try {
      const name = draftName.trim() || `Prompt ${new Date().toLocaleDateString()}`;
      // Create a new named prompt in library, then activate it
      const createRes = await fetch(`${apiBase}/api/docintel/copilot-prompts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, name, prompt_text: draftPrompt }),
      });
      if (createRes.ok) {
        const { prompt_id } = await createRes.json();
        await fetch(`${apiBase}/api/docintel/copilot-prompts/${prompt_id}/activate`, { method: "POST" });
      } else {
        // fallback: legacy single-prompt save
        await fetch(`${apiBase}/api/docintel/copilot-prompt`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain_id: domainId, prompt: draftPrompt }),
        });
      }
      setSavedPrompt(draftPrompt);
      setSavedAt(new Date().toISOString());
      setEditMode(false);
      setShowAddNew(false);
      setDraftName("");
      setGapReport(null);
      setBriefings(briefingQueries.map(() => null));
      loadPromptLibrary();
    } catch {
      alert("Failed to save prompt. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleActivatePrompt = async (promptId: string) => {
    await fetch(`${apiBase}/api/docintel/copilot-prompts/${promptId}/activate`, { method: "POST" });
    loadPromptLibrary();
    setBriefings(briefingQueries.map(() => null));
  };

  const handleDeletePrompt = async (promptId: string) => {
    if (!confirm("Delete this prompt? This cannot be undone.")) return;
    const res = await fetch(`${apiBase}/api/docintel/copilot-prompts/${promptId}`, { method: "DELETE" });
    if (!res.ok) { const e = await res.json(); alert(e.detail || "Delete failed"); return; }
    loadPromptLibrary();
  };

  const handleUpdatePrompt = async (promptId: string, name: string, text: string) => {
    await fetch(`${apiBase}/api/docintel/copilot-prompts/${promptId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt_text: text }),
    });
    setEditingPromptId(null);
    loadPromptLibrary();
  };

  const handleAsk = async () => {
    if (!askQuery.trim()) return;
    setAskLoading(true);
    setAskResult(null);
    try {
      const res = await fetch(`${apiBase}/api/docintel/copilot-query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, query: askQuery }),
      });
      const result: CopilotResult = await res.json();
      setAskResult(result);
      // Auto-log to attorney review queue if flagged
      if (result?.attorney_review) {
        fetch(`${apiBase}/api/docintel/attorney-review-queue`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            domain_id: domainId,
            query: askQuery,
            response_summary: result.sections?.next_steps?.slice(0, 500) || result.raw_answer?.slice(0, 500),
            flagged_reason: "AI flagged: attorney review recommended",
          }),
        }).catch(() => {});
      }
    } catch {
      setAskResult(null);
    } finally {
      setAskLoading(false);
    }
  };

  const isSetupSub = sub === "setup";

  // ── Inline Prompt Edit Card (reusable) ──
  function PromptEditCard({ promptId, initialName, initialText, onDone }: {
    promptId: string; initialName: string; initialText: string; onDone: () => void;
  }) {
    const [editName, setEditName] = useState(initialName);
    const [editText, setEditText] = useState(initialText);
    const [saving2, setSaving2] = useState(false);
    return (
      <div className="border border-blue-200 rounded-lg p-4 bg-blue-50 space-y-3">
        <input value={editName} onChange={e => setEditName(e.target.value)}
          className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-blue-400"
          placeholder="Prompt name…" />
        <textarea rows={8} value={editText} onChange={e => setEditText(e.target.value)}
          className="w-full text-xs font-mono border border-gray-200 rounded-lg p-3 resize-y focus:outline-none focus:ring-1 focus:ring-blue-400"
          spellCheck={false} />
        <div className="flex gap-2">
          <button disabled={saving2} onClick={async () => { setSaving2(true); await handleUpdatePrompt(promptId, editName, editText); setSaving2(false); onDone(); }}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
            {saving2 ? "Saving…" : "Save Changes"}
          </button>
          <button onClick={onDone} className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    );
  }

  // ── Setup sub-view ──
  if (isSetupSub || (!savedPrompt)) {
    const inEditMode = editMode || !savedPrompt;
    return (
      <div className="space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Copilot Studio — Setup & Readiness</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Manage your guiding instructions. The active prompt steers the AI Agent and all Copilot queries.
            </p>
          </div>
          {!showAddNew && (
            <button
              onClick={() => { setShowAddNew(true); setDraftPrompt(""); setDraftName(""); setGapReport(null); }}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
            >
              + Add Prompt
            </button>
          )}
        </div>

        {/* ── Prompt Library ── */}
        {promptLibrary.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Saved Prompts</p>
            {promptLibrary.map(p => (
              <div key={p.prompt_id}>
                {editingPromptId === p.prompt_id ? (
                  <PromptEditCard
                    promptId={p.prompt_id}
                    initialName={p.name}
                    initialText={p.preview + "…"}  // will be re-fetched on save
                    onDone={() => { setEditingPromptId(null); loadPromptLibrary(); }}
                  />
                ) : (
                  <div className={`border rounded-lg p-3.5 space-y-1.5 ${p.is_active ? "border-green-300 bg-green-50" : "border-gray-200 bg-white hover:bg-gray-50"}`}>
                    <div className="flex items-center gap-2">
                      {p.is_active && <span className="text-[10px] font-bold bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Active</span>}
                      <span className="text-sm font-semibold text-gray-800 flex-1">{p.name}</span>
                      <span className="text-[10px] text-gray-400">{p.created_at ? new Date(p.created_at).toLocaleDateString() : ""}</span>
                    </div>
                    <p className="text-[11px] text-gray-500 font-mono line-clamp-2">{p.preview}</p>
                    <div className="flex items-center gap-2 pt-1">
                      {!p.is_active && (
                        <button onClick={() => handleActivatePrompt(p.prompt_id)}
                          className="text-[11px] font-semibold px-2.5 py-1 rounded-md bg-green-600 text-white hover:bg-green-700">
                          Activate
                        </button>
                      )}
                      <button onClick={() => setEditingPromptId(p.prompt_id)}
                        className="text-[11px] font-semibold px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-100">
                        Edit
                      </button>
                      {!p.is_active && (
                        <button onClick={() => handleDeletePrompt(p.prompt_id)}
                          className="text-[11px] px-2.5 py-1 rounded-md border border-red-100 text-red-500 hover:bg-red-50">
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {libraryLoading && (
          <div className="text-xs text-gray-400 text-center py-4">Loading prompts…</div>
        )}

        {/* ── Add New Prompt Form ── */}
        {(showAddNew || inEditMode) && (
          <div className="border border-blue-200 rounded-lg p-5 bg-blue-50/30 space-y-3">
            <p className="text-xs font-semibold text-gray-700">
              {showAddNew ? "New Prompt" : "Paste Guiding Instructions"}
            </p>
            <input
              value={draftName}
              onChange={e => setDraftName(e.target.value)}
              placeholder={`Prompt name (e.g. "${domainId.replace(/_/g," ")} Compliance Review")`}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <textarea
              value={draftPrompt}
              onChange={e => { setDraftPrompt(e.target.value); setGapReport(null); }}
              placeholder={"# Copilot Instructions\n\nYou are...\n\n## Core Responsibilities\n..."}
              className="w-full h-56 text-xs font-mono border border-gray-200 rounded-lg p-3 resize-y focus:outline-none focus:ring-2 focus:ring-blue-400"
              spellCheck={false}
            />
            <div className="flex flex-wrap items-center gap-2">
              {/* Always-visible Save button */}
              <button
                onClick={() => handleSave(true)}
                disabled={!draftPrompt.trim() || saving}
                className="px-3 py-2 text-sm font-semibold rounded-lg border border-green-300 bg-white text-green-700 hover:bg-green-50 disabled:opacity-50"
              >
                {saving ? "Saving…" : "💾 Save Prompt"}
              </button>
              <button
                onClick={handleAnalyze}
                disabled={!draftPrompt.trim() || analyzing}
                className="px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {analyzing ? "Analyzing…" : "Analyze & Check Data Readiness"}
              </button>
              <button
                onClick={() => { setShowAddNew(false); setEditMode(false); setDraftPrompt(""); setDraftName(""); setGapReport(null); }}
                className="text-xs text-gray-500 hover:text-gray-800 px-2"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* No prompts yet — prompt to add */}
        {promptLibrary.length === 0 && !libraryLoading && !showAddNew && !inEditMode && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center text-sm text-amber-700">
            No guiding prompts yet. Click <strong>+ Add Prompt</strong> to paste your instructions.
          </div>
        )}

        {/* Gap report — error state */}
        {gapReport && !(gapReport as unknown as {required?: unknown}).required && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            ⚠️ Analysis failed: {(gapReport as unknown as {detail?: string}).detail ?? "Unknown error. Please try again."}
          </div>
        )}

        {/* Gap report */}
        {gapReport && !!(gapReport as unknown as {required?: unknown}).required && (
          <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-800">Data Readiness Report</h3>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                gapReport.coverage_pct >= 80 ? "bg-green-100 text-green-700" :
                gapReport.coverage_pct >= 50 ? "bg-amber-100 text-amber-700" :
                "bg-red-100 text-red-700"
              }`}>
                {gapReport.coverage_pct}% coverage
              </span>
            </div>
            <div>
              <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all ${
                  gapReport.coverage_pct >= 80 ? "bg-green-500" :
                  gapReport.coverage_pct >= 50 ? "bg-amber-400" : "bg-red-400"
                }`} style={{ width: `${gapReport.coverage_pct}%` }} />
              </div>
              <p className="text-xs text-gray-500 mt-1">{gapReport.total_docs} documents in library · {gapReport.required.length} doc types required by prompt</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {gapReport.required.map(rt => {
                const covered = gapReport.covered[rt] != null;
                const count   = gapReport.covered[rt];
                return (
                  <div key={rt} className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border ${covered ? "bg-green-50 border-green-200 text-green-800" : "bg-red-50 border-red-200 text-red-800"}`}>
                    <span>{covered ? "✅" : "❌"}</span>
                    <span className="font-mono flex-1">{rt.replace(/_/g, " ")}</span>
                    {covered && <span className="text-green-600 font-semibold">{count} docs</span>}
                    {!covered && <span className="text-red-500 font-semibold">missing</span>}
                  </div>
                );
              })}
            </div>
            {gapReport.gaps.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800 space-y-1">
                <p className="font-semibold">⚠️ Missing document types detected</p>
                <p>{gapReport.message}</p>
                <a href="/document-intelligence" className="inline-block mt-1 text-blue-600 hover:underline font-semibold">→ Go to Document Library to upload missing documents</a>
              </div>
            )}
            {gapReport.ready_to_proceed && (
              <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-xs text-green-800 font-semibold">✅ {gapReport.message}</div>
            )}
            <div className="flex items-center gap-3 pt-1 border-t border-gray-100">
              <button onClick={() => handleSave()} disabled={saving}
                className={`px-4 py-2 text-sm font-semibold rounded-lg text-white disabled:opacity-50 ${gapReport.ready_to_proceed ? "bg-green-600 hover:bg-green-700" : "bg-amber-500 hover:bg-amber-600"}`}>
                {saving ? "Saving…" : gapReport.ready_to_proceed ? "✅ Save as Guiding Principle" : "Proceed Anyway & Save"}
              </button>
              {!gapReport.ready_to_proceed && <span className="text-xs text-gray-400">Some document types are missing — analysis may be incomplete.</span>}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Briefings sub-view ──
  if (sub === "briefings") {
    if (!savedPrompt) {
      return (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center text-sm text-amber-700">
          No guiding prompt saved yet. Go to the <strong>Setup &amp; Readiness</strong> tab to paste your instructions first.
        </div>
      );
    }
    return (
      <div className="space-y-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Intelligence Briefings</h2>
            <p className="text-xs text-gray-400 mt-0.5">Auto-generated insights from your parsed documents, guided by your saved prompt.</p>
          </div>
          <button
            onClick={() => onSwitchToSetup ? onSwitchToSetup() : setEditMode(true)}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            ✏️ Edit Prompt
          </button>
        </div>
        <div className="space-y-4">
          {briefingQueries.map((q, i) => {
            const b = briefings[i];
            return (
              <details key={i} className="bg-white border border-gray-200 rounded-lg overflow-hidden" open={i === 0}>
                <summary className="px-4 py-3 text-sm font-semibold text-gray-800 cursor-pointer hover:bg-gray-50 flex items-center gap-2">
                  <span className="text-blue-500 flex-shrink-0">#{i + 1}</span>
                  {q}
                  {b === "loading" && <span className="ml-auto text-xs text-gray-400 animate-pulse">Thinking…</span>}
                  {b && b !== "loading" && <span className="ml-auto text-xs text-gray-400">Ready</span>}
                  {b === null && <span className="ml-auto text-xs text-amber-400">Queued</span>}
                </summary>
                <div className="px-4 pb-4 pt-1 border-t border-gray-100">
                  {b === "loading" ? (
                    <div className="flex items-center gap-2 text-xs text-gray-400 py-4">
                      <span className="animate-spin">⟳</span> Consulting document knowledge base…
                    </div>
                  ) : b && typeof b === "object" ? (
                    <StructuredCopilotResponse result={b as CopilotResult} />
                  ) : (
                    <p className="text-xs text-gray-400 py-2">Waiting to load…</p>
                  )}
                </div>
              </details>
            );
          })}
        </div>
      </div>
    );
  }

  // ── Legal Queue sub-view ──
  if (sub === "legal") {
    return <LegalQueue domainId={domainId} apiBase={apiBase} />;
  }

  // ── Ask sub-view ──
  if (!savedPrompt) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center text-sm text-amber-700">
        No guiding prompt saved yet. Go to the <strong>Setup &amp; Readiness</strong> tab to paste your instructions first.
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-800">Ask Copilot</h2>
            <p className="text-xs text-gray-400 mt-0.5">Ask any document intelligence question across your parsed library. Every answer cites its source.</p>
        </div>
        <button
          onClick={() => onSwitchToSetup ? onSwitchToSetup() : setShowAddNew(true)}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
        >
          ✏️ Edit Prompt
        </button>
      </div>

      {/* Active prompt badge */}
      {promptLibrary.find(p => p.is_active) ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-[11px] text-gray-500 flex items-center gap-2">
          <span className="text-green-500 flex-shrink-0">●</span>
          <span className="flex-1">Active prompt: <strong className="text-gray-700">{promptLibrary.find(p => p.is_active)?.name}</strong></span>
        </div>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-[11px] text-gray-500 flex items-center gap-2">
          <span className="text-green-500 flex-shrink-0">●</span>
          <span>Guiding prompt active{savedAt ? ` · saved ${new Date(savedAt).toLocaleString()}` : ""}</span>
        </div>
      )}

      {/* Suggested questions */}
      <div className="flex flex-wrap gap-2">
        {[
          "Summarize key findings across all documents and identify open action items.",
          "What risks are currently identified? Cite document sources.",
          "Which entities or locations have the most outstanding items?",
          "What deadlines or expiration dates require attention in the next 90 days?",
          "Are there any regulatory or contractual requirements needing immediate action?",
        ].map(q => (
          <button
            key={q}
            onClick={() => setAskQuery(q)}
            className="text-xs px-3 py-1.5 bg-white border border-gray-200 rounded-full hover:border-blue-300 hover:text-blue-700 text-gray-600 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <textarea
          value={askQuery}
          onChange={e => setAskQuery(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAsk(); } }}
          placeholder="Ask a document intelligence question…"
          rows={2}
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
        <button
          onClick={handleAsk}
          disabled={!askQuery.trim() || askLoading}
          className="px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed self-start"
        >
          {askLoading ? "…" : "Ask"}
        </button>
      </div>

      {/* Loading */}
      {askLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
          <span className="animate-spin text-blue-500">⟳</span>
          Consulting document knowledge base…
        </div>
      )}

      {/* Result */}
      {askResult && askResult.sections !== undefined && (
        <>
          <StructuredCopilotResponse result={askResult} />
          {/* Manual "Add to Legal Review" */}
          <div className="flex items-center gap-3 pt-2">
            {!addToLegal ? (
              <button
                onClick={async () => {
                  setAddToLegal(true);
                  await fetch(`${apiBase}/api/docintel/attorney-review-queue`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      domain_id: domainId,
                      query: askQuery,
                      response_summary: (askResult.sections?.next_steps || askResult.raw_answer || "").slice(0, 500),
                      flagged_reason: "Manually flagged for legal review by user",
                    }),
                  }).catch(() => {});
                }}
                className="text-[11px] font-semibold px-3 py-1.5 rounded-lg border border-amber-200 text-amber-700 hover:bg-amber-50"
              >
                ⚖️ Add to Legal Review Queue
              </button>
            ) : (
              <span className="text-[11px] text-green-600 font-semibold">✅ Added to Legal Review Queue</span>
            )}
            {askResult?.attorney_review && !addToLegal && (
              <span className="text-[11px] text-amber-600">AI flagged this response for legal review</span>
            )}
          </div>
        </>
      )}
      {askResult && askResult.sections === undefined && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          The copilot returned an unexpected response. Please try again.
          {(askResult as unknown as {detail?: string}).detail && (
            <p className="text-xs mt-1 font-mono">{(askResult as unknown as {detail?: string}).detail}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Legal Queue sub-tab ───────────────────────────────────────────────────────

interface LegalQueueItem {
  id: string;
  domain_id: string;
  query: string;
  response_summary?: string;
  flagged_reason?: string;
  flagged_at?: string;
  status: string;
  reviewed_by?: string;
  reviewed_at?: string;
}

function LegalQueue({ domainId, apiBase }: { domainId: string; apiBase: string }) {
  const [items, setItems] = useState<LegalQueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [updating, setUpdating] = useState<string | null>(null);
  const [lastPopulated, setLastPopulated] = useState<string | null>(null);
  const [addManualOpen, setAddManualOpen] = useState(false);
  const [manualForm, setManualForm] = useState({ query: "", response_summary: "", flagged_reason: "Manually added by user" });
  const [addingManual, setAddingManual] = useState(false);

  const load = () => {
    setLoading(true); setErr("");
    fetch(`${apiBase}/api/docintel/attorney-review-queue?domain_id=${encodeURIComponent(domainId)}`)
      .then(r => r.json())
      .then(d => { setItems(d.items ?? []); setLastPopulated(d.last_populated ?? null); })
      .catch(() => setErr("Failed to load queue"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [domainId]); // eslint-disable-line

  const updateStatus = async (id: string, status: string) => {
    setUpdating(id);
    try {
      await fetch(`${apiBase}/api/docintel/attorney-review-queue/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      setItems(prev => prev.map(it => it.id === id ? { ...it, status } : it));
    } catch { /* swallow */ }
    setUpdating(null);
  };

  const statusChip = (s: string) => {
    const map: Record<string, string> = {
      PENDING:   "bg-amber-100 text-amber-700",
      CLEARED:   "bg-green-100 text-green-700",
      ESCALATED: "bg-red-100 text-red-700",
    };
    return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${map[s] ?? "bg-gray-100 text-gray-600"}`}>{s}</span>;
  };

  const pending = items.filter(i => i.status === "PENDING").length;

  async function addManualItem() {
    if (!manualForm.query.trim()) return;
    setAddingManual(true);
    try {
      await fetch(`${apiBase}/api/docintel/attorney-review-queue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain_id: domainId, ...manualForm }),
      });
      setManualForm({ query: "", response_summary: "", flagged_reason: "Manually added by user" });
      setAddManualOpen(false);
      load();
    } catch { alert("Failed to add item."); }
    finally { setAddingManual(false); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-base font-semibold text-gray-800">Legal Review Queue</h2>
        {pending > 0 && (
          <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-500 text-white animate-pulse">
            {pending} pending
          </span>
        )}
        {lastPopulated && <span className="text-[10px] text-gray-400">Last activity: {new Date(lastPopulated).toLocaleString()}</span>}
        <div className="ml-auto flex gap-2">
          <button onClick={() => setAddManualOpen(o => !o)}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-amber-200 text-amber-700 hover:bg-amber-50">
            + Add Manually
          </button>
          <button onClick={load} className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">↺ Refresh</button>
        </div>
      </div>
      <p className="text-xs text-gray-400">
        Copilot responses flagged for attorney review are automatically logged here.
        You can also add items manually or from the Ask Copilot results.
      </p>

      {/* Manual add form */}
      {addManualOpen && (
        <div className="border border-amber-200 rounded-lg p-4 bg-amber-50 space-y-3">
          <p className="text-xs font-semibold text-amber-800">Add Item to Legal Review Queue</p>
          <input value={manualForm.query} onChange={e => setManualForm(f => ({...f, query: e.target.value}))}
            placeholder="Query / topic to review…"
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400" />
          <textarea rows={2} value={manualForm.response_summary} onChange={e => setManualForm(f => ({...f, response_summary: e.target.value}))}
            placeholder="Summary or context (optional)…"
            className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-amber-400" />
          <input value={manualForm.flagged_reason} onChange={e => setManualForm(f => ({...f, flagged_reason: e.target.value}))}
            placeholder="Reason for flagging"
            className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-amber-400" />
          <div className="flex gap-2">
            <button disabled={addingManual || !manualForm.query.trim()} onClick={addManualItem}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50">
              {addingManual ? "Adding…" : "Add to Queue"}
            </button>
            <button onClick={() => setAddManualOpen(false)} className="px-3 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      {loading && <p className="text-sm text-gray-400 py-4">Loading queue…</p>}
      {err && <p className="text-sm text-red-500">{err}</p>}

      {!loading && items.length === 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center space-y-2">
          <p className="text-sm text-gray-500 font-medium">No items in the review queue</p>
          <p className="text-xs text-gray-400">
            Items are added automatically when Ask Copilot flags a response for legal review,
            or when you click <strong>⚖️ Add to Legal Review Queue</strong> in Ask Copilot,
            or manually using the button above.
          </p>
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-3 py-2.5 text-gray-500 font-semibold w-1/3">Query</th>
                <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Reason</th>
                <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Date</th>
                <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Status</th>
                <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-2.5 text-gray-700">{item.query?.slice(0, 100)}{(item.query?.length ?? 0) > 100 ? "…" : ""}</td>
                  <td className="px-3 py-2.5 text-gray-500">{item.flagged_reason || "—"}</td>
                  <td className="px-3 py-2.5 text-gray-400 whitespace-nowrap">{item.flagged_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                  <td className="px-3 py-2.5">{statusChip(item.status)}</td>
                  <td className="px-3 py-2.5">
                    {item.status === "PENDING" && (
                      <div className="flex gap-1">
                        <button
                          disabled={updating === item.id}
                          onClick={() => updateStatus(item.id, "CLEARED")}
                          className="text-[10px] font-semibold px-2 py-1 rounded bg-green-100 text-green-700 hover:bg-green-200 disabled:opacity-50"
                        >
                          ✓ Clear
                        </button>
                        <button
                          disabled={updating === item.id}
                          onClick={() => updateStatus(item.id, "ESCALATED")}
                          className="text-[10px] font-semibold px-2 py-1 rounded bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50"
                        >
                          ↑ Escalate
                        </button>
                      </div>
                    )}
                    {item.status !== "PENDING" && (
                      <span className="text-gray-400 text-[10px]">Reviewed</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// (Domain Schema Setup moved to Document Intelligence → Document Library wizard)

// ── Compliance Map Tab ────────────────────────────────────────────────────────

interface DigestItem {
  doc_id: string;
  filename: string;
  doc_type: string;
  jurisdiction?: string;
  assigned_owner?: string;
  deadline?: string;
  risk_level?: string;
  statute_number?: string;
  processed_ts?: string;
  status: string;
}

interface RegChangeItem {
  doc_id: string;
  filename: string;
  change_type?: string;
  effective_date?: string;
  jurisdiction?: string;
  statute_number?: string;
  enforcement_authority?: string;
  risk_level?: string;
  confidence_level?: string;
  days_until?: number | null;
}

interface JurisdictionMatrix {
  jurisdictions: string[];
  topics: string[];
  matrix: Record<string, Record<string, { count: number; risk_levels: string[]; has_open: boolean; docs: { doc_id: string; filename: string; risk_level: string; statute_number: string }[] }>>;
  total_docs_with_jurisdiction: number;
  total_cells: number;
  cells_with_issues: number;
}

function ComplianceMapTab({ domainId, sub, apiBase }: { domainId: string; sub: string; apiBase: string }) {
  const [digestItems, setDigestItems] = useState<DigestItem[]>([]);
  const [digestLoading, setDigestLoading] = useState(false);
  const [digestErr, setDigestErr] = useState("");

  const [mapData, setMapData] = useState<JurisdictionMatrix | null>(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapErr, setMapErr] = useState("");
  const [expandedCell, setExpandedCell] = useState<string | null>(null);

  const [pulseItems, setPulseItems] = useState<RegChangeItem[]>([]);
  const [pulseLoading, setPulseLoading] = useState(false);
  const [pulseErr, setPulseErr] = useState("");

  const onDocClick = (docId: string) => openDocViewer(docId);

  useEffect(() => {
    if (sub === "digest" || sub === undefined || sub === "map") {
      setDigestLoading(true);
      fetch(`${apiBase}/api/docintel/correspondence-digest?domain_id=${encodeURIComponent(domainId)}`)
        .then(r => r.json())
        .then(d => setDigestItems(d.items ?? []))
        .catch(() => setDigestErr("Failed to load digest"))
        .finally(() => setDigestLoading(false));
    }
    if (sub === "map" || sub === undefined) {
      setMapLoading(true);
      fetch(`${apiBase}/api/docintel/jurisdiction-map?domain_id=${encodeURIComponent(domainId)}`)
        .then(r => r.json())
        .then(d => setMapData(d))
        .catch(() => setMapErr("Failed to load map"))
        .finally(() => setMapLoading(false));
    }
    if (sub === "pulse" || sub === undefined) {
      setPulseLoading(true);
      fetch(`${apiBase}/api/docintel/regulatory-changes?domain_id=${encodeURIComponent(domainId)}`)
        .then(r => r.json())
        .then(d => setPulseItems(d.changes ?? []))
        .catch(() => setPulseErr("Failed to load regulatory changes"))
        .finally(() => setPulseLoading(false));
    }
  }, [domainId, sub, apiBase]); // eslint-disable-line

  const digestStatusStyle: Record<string, string> = {
    OVERDUE:    "bg-red-100 text-red-700",
    DUE_SOON:   "bg-amber-100 text-amber-700",
    OPEN:       "bg-blue-100 text-blue-700",
    NO_DEADLINE:"bg-gray-100 text-gray-500",
  };

  const changeTypeStyle: Record<string, string> = {
    AMENDED:          "bg-amber-500",
    "NEW REQUIREMENT":"bg-green-500",
    REPEALED:         "bg-red-500",
    COMPARISON:       "bg-indigo-500",
  };

  // Coverage matrix: color cells
  const cellColor = (cell: { count: number; has_open: boolean } | undefined) => {
    if (!cell) return "bg-red-50 text-red-400 border-red-100";
    if (cell.has_open) return "bg-amber-50 text-amber-700 border-amber-200";
    return "bg-green-50 text-green-700 border-green-200";
  };
  const cellLabel = (cell: { count: number; has_open: boolean } | undefined) => {
    if (!cell) return "✗ Gap";
    if (cell.has_open) return "⚠ Issues";
    return "✓ Covered";
  };

  if (sub === "map") {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-5">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-800">Jurisdiction Coverage Matrix</h2>
          {mapData && (
            <div className="flex gap-2 ml-auto flex-wrap">
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{mapData.jurisdictions.length} jurisdictions</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">{mapData.total_cells - mapData.cells_with_issues} covered</span>
              {mapData.cells_with_issues > 0 && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">{mapData.cells_with_issues} with issues</span>
              )}
            </div>
          )}
        </div>
        {mapLoading && <p className="text-sm text-gray-400">Loading map…</p>}
        {mapErr && <p className="text-sm text-red-500">{mapErr}</p>}
        {mapData && mapData.jurisdictions.length === 0 && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-sm text-gray-400">
            No jurisdiction data found. Process documents with the Compliance Standard Fields preset to populate this map.
          </div>
        )}
        {mapData && mapData.jurisdictions.length > 0 && (
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2 bg-gray-50 border border-gray-200 font-semibold text-gray-600 sticky left-0">Jurisdiction</th>
                  {mapData.topics.map(t => (
                    <th key={t} className="px-3 py-2 bg-gray-50 border border-gray-200 font-semibold text-gray-600 text-center max-w-[100px]">
                      <span className="block truncate">{t.replace(/_/g, " ")}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {mapData.jurisdictions.map(j => (
                  <>
                    <tr key={j}>
                      <td className="px-3 py-2 border border-gray-200 font-medium text-gray-700 sticky left-0 bg-white">{j}</td>
                      {mapData.topics.map(t => {
                        const cell = mapData.matrix[j]?.[t];
                        const cellKey = `${j}::${t}`;
                        return (
                          <td key={t} className="px-2 py-2 border border-gray-200 text-center">
                            <button
                              onClick={() => setExpandedCell(expandedCell === cellKey ? null : cellKey)}
                              className={`text-[10px] font-semibold px-2 py-1 rounded border w-full ${cellColor(cell)}`}
                            >
                              {cellLabel(cell)}
                              {cell && <span className="ml-1 text-gray-400">({cell.count})</span>}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                    {expandedCell && expandedCell.startsWith(`${j}::`) && (() => {
                      const t = expandedCell.split("::")[1];
                      const cell = mapData.matrix[j]?.[t];
                      if (!cell) return null;
                      return (
                        <tr key={`${j}-${t}-expand`}>
                          <td colSpan={mapData.topics.length + 1} className="px-4 py-3 bg-blue-50 border border-blue-200">
                            <p className="text-xs font-semibold text-blue-800 mb-1.5">{j} — {t.replace(/_/g, " ")}: {cell.count} document(s)</p>
                            <div className="flex flex-wrap gap-1.5">
                              {cell.docs.map(d => (
                                <button key={d.doc_id} onClick={() => onDocClick(d.doc_id)}
                                  className="text-[10px] px-2 py-1 rounded-full bg-white border border-blue-200 text-blue-700 hover:bg-blue-100">
                                  {d.filename.length > 40 ? d.filename.slice(0, 40) + "…" : d.filename}
                                  {d.risk_level && <span className="ml-1 font-bold">[{d.risk_level}]</span>}
                                </button>
                              ))}
                            </div>
                          </td>
                        </tr>
                      );
                    })()}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  if (sub === "digest") {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-800">Action Digest</h2>
          <p className="text-xs text-gray-400">Correspondence, notices, and violation items sorted by deadline</p>
          <button
            onClick={() => { setDigestLoading(true); fetch(`${apiBase}/api/docintel/correspondence-digest?domain_id=${encodeURIComponent(domainId)}`).then(r=>r.json()).then(d=>setDigestItems(d.items??[])).finally(()=>setDigestLoading(false)); }}
            className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">↺ Refresh</button>
        </div>
        {digestLoading && <p className="text-sm text-gray-400">Loading digest…</p>}
        {digestErr && <p className="text-sm text-red-500">{digestErr}</p>}
        {!digestLoading && digestItems.length === 0 && (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-sm text-gray-400">
            No correspondence or action items found. Process documents with deadline and assigned_owner fields to populate this digest.
          </div>
        )}
        {digestItems.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-gray-200">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Document</th>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Jurisdiction</th>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Owner</th>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Deadline</th>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Risk</th>
                  <th className="text-left px-3 py-2.5 text-gray-500 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {digestItems.map(item => (
                  <tr key={item.doc_id} className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer" onClick={() => onDocClick(item.doc_id)}>
                    <td className="px-3 py-2.5 text-blue-600 hover:underline max-w-[180px] truncate">{item.filename}</td>
                    <td className="px-3 py-2.5 text-gray-600">{item.jurisdiction || "—"}</td>
                    <td className="px-3 py-2.5 text-gray-600">{item.assigned_owner || "—"}</td>
                    <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">{item.deadline || "—"}</td>
                    <td className="px-3 py-2.5">
                      {item.risk_level ? (
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          item.risk_level === "CRITICAL" ? "bg-red-600 text-white" :
                          item.risk_level === "HIGH" ? "bg-red-100 text-red-700" :
                          item.risk_level === "MEDIUM" ? "bg-amber-100 text-amber-700" :
                          "bg-gray-100 text-gray-600"}`}>{item.risk_level}</span>
                      ) : "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${digestStatusStyle[item.status] ?? "bg-gray-100 text-gray-500"}`}>
                        {item.status.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  // Default: Regulatory Pulse (sub === "pulse")
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-base font-semibold text-gray-800">Regulatory Pulse</h2>
        <p className="text-xs text-gray-400">Upcoming and recent regulatory changes affecting your operations</p>
        <button
          onClick={() => { setPulseLoading(true); fetch(`${apiBase}/api/docintel/regulatory-changes?domain_id=${encodeURIComponent(domainId)}`).then(r=>r.json()).then(d=>setPulseItems(d.changes??[])).finally(()=>setPulseLoading(false)); }}
          className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">↺ Refresh</button>
      </div>
      {pulseLoading && <p className="text-sm text-gray-400">Loading regulatory changes…</p>}
      {pulseErr && <p className="text-sm text-red-500">{pulseErr}</p>}
      {!pulseLoading && pulseItems.length === 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-sm text-gray-400">
          No regulatory change documents found. Process documents with <code className="bg-gray-100 px-1 rounded">doc_type = regulatory_change</code> to populate this feed.
        </div>
      )}
      <div className="space-y-3">
        {pulseItems.map(item => {
          const ct = (item.change_type ?? "").toUpperCase();
          const barColor = changeTypeStyle[ct] || changeTypeStyle.COMPARISON || "bg-gray-400";
          const urgency = item.days_until !== null && item.days_until !== undefined
            ? (item.days_until < 0 ? "OVERDUE" : item.days_until <= 30 ? "IMMINENT" : item.days_until <= 90 ? "UPCOMING" : "FUTURE")
            : null;
          return (
            <div key={item.doc_id} className="flex gap-3 bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm cursor-pointer" onClick={() => onDocClick(item.doc_id)}>
              <div className={`w-1.5 rounded-full flex-shrink-0 self-stretch ${barColor}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-2 flex-wrap">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full text-white ${barColor}`}>{ct || "CHANGE"}</span>
                  {item.jurisdiction && (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">{item.jurisdiction}</span>
                  )}
                  {urgency && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      urgency === "OVERDUE" ? "bg-red-100 text-red-700" :
                      urgency === "IMMINENT" ? "bg-amber-100 text-amber-700" :
                      "bg-gray-100 text-gray-600"}`}>{urgency}</span>
                  )}
                  {item.risk_level && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ml-auto ${
                      item.risk_level === "CRITICAL" || item.risk_level === "HIGH" ? "bg-red-100 text-red-700" :
                      item.risk_level === "MEDIUM" ? "bg-amber-100 text-amber-700" :
                      "bg-gray-100 text-gray-600"}`}>{item.risk_level}</span>
                  )}
                </div>
                <p className="text-xs font-semibold text-gray-800 mt-1.5">{item.filename}</p>
                {item.statute_number && <p className="text-[10px] text-gray-500 mt-0.5">{item.statute_number}</p>}
                {item.enforcement_authority && <p className="text-[10px] text-gray-400">{item.enforcement_authority}</p>}
                <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                  {item.effective_date && (
                    <span className="text-[10px] text-gray-500">Effective: <strong>{item.effective_date}</strong></span>
                  )}
                  {item.days_until !== null && item.days_until !== undefined && (
                    <span className="text-[10px] text-gray-400">
                      {item.days_until < 0 ? `${Math.abs(item.days_until)}d past` : `in ${item.days_until}d`}
                    </span>
                  )}
                  {item.confidence_level && (
                    <span className="text-[10px] text-gray-400">Confidence: {item.confidence_level}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OntologyMap({ graph, sub, domainName = "Domain" }: { graph: OntGraph; sub: string; domainName?: string }) {
  // ALL hooks must be declared before any early return (React rules of hooks)
  const [hovered,     setHovered]     = useState<string|null>(null);
  const [selected,    setSelected]    = useState<string|null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<number|null>(null);
  const [zoom,        setZoom]        = useState(1);
  const [pan,         setPan]         = useState({ x: 0, y: 0 });
  const [dragging,    setDragging]    = useState(false);
  const [dragStart,   setDragStart]   = useState({ x: 0, y: 0 });
  const [graphSearch, setGraphSearch] = useState("");
  const [emailOpen,    setEmailOpen]    = useState(false);
  const [emailTo,      setEmailTo]      = useState("");
  const [emailCopied,  setEmailCopied]  = useState(false);
  const [gmailThreads, setGmailThreads] = useState<{thread_id:string;subject:string;from:string;snippet:string;date:string}[]>([]);
  const [gmailLoading, setGmailLoading] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);

  const nodeById = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
  const selectedNode = selected ? nodeById[selected] : null;
  const connectedEdges = selected
    ? graph.edges.filter(e => e.source === selected || e.target === selected)
    : [];

  // Connection count per node
  const connCount: Record<string,number> = {};
  graph.edges.forEach(e => {
    connCount[e.source] = (connCount[e.source] ?? 0) + 1;
    connCount[e.target] = (connCount[e.target] ?? 0) + 1;
  });

  // Search filter — nodes whose id, label, or type match the query
  const q = graphSearch.trim().toLowerCase();
  const visibleNodeIds = q
    ? new Set(graph.nodes.filter(n =>
        n.id.toLowerCase().includes(q) ||
        n.label.toLowerCase().includes(q) ||
        n.type.toLowerCase().includes(q)
      ).map(n => n.id))
    : null; // null = show all

  const presentTypes = Array.from(new Set(graph.nodes.map(n => n.type))).sort();
  const maxX = graph.nodes.reduce((m, n) => Math.max(m, n.x + 80), 700);
  const maxY = graph.nodes.reduce((m, n) => Math.max(m, n.y + 70), 480);
  const W = maxX, H = maxY;

  function handleNodeClick(id: string) {
    setSelected(prev => prev === id ? null : id);
  }

  function edgePath(sx: number, sy: number, tx: number, ty: number) {
    const dx = tx - sx, dy = ty - sy;
    const cx = sx + dx * 0.5 + (dy !== 0 ? dy * 0.15 : 40);
    const cy = sy + dy * 0.5 - (dx !== 0 ? dx * 0.1 : 0);
    return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`;
  }

  function handleWheel(e: React.WheelEvent) {
    e.preventDefault();
    setZoom(z => Math.min(4, Math.max(0.3, z - e.deltaY * 0.001)));
  }

  function handleMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return;
    setDragging(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!dragging) return;
    setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
  }

  function handleMouseUp() { setDragging(false); }

  // ── Entity List sub-view ─────────────────────────────────────────────────────
  if (sub === "entities") {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        {graph.nodes.map(n => (
          <div
            key={n.id}
            onClick={() => handleNodeClick(n.id)}
            className={`flex items-center gap-2 text-xs rounded-md px-2.5 py-2 border cursor-pointer transition-colors
              ${selected===n.id ? "bg-indigo-50 border-indigo-300 ring-1 ring-indigo-200" : "bg-gray-50 border-gray-100 hover:bg-white hover:border-gray-300"}`}
          >
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: nodeColor[n.type] ?? nodeColor.default }} />
            <div className="min-w-0">
              <p className="font-medium text-gray-800 truncate">{n.label}</p>
              <p className="text-gray-400 text-[10px]">{n.type}</p>
            </div>
          </div>
        ))}
        {selectedNode && (
          <div className="col-span-full mt-3 bg-white rounded-lg border border-indigo-200 p-4">
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-3 h-3 rounded-full" style={{backgroundColor: nodeColor[selectedNode.type]??nodeColor.default}}/>
                  <span className="text-xs font-bold text-gray-700">{selectedNode.type}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${selectedNode.risk==="critical"?"bg-red-100 text-red-700":selectedNode.risk==="high"?"bg-orange-100 text-orange-700":selectedNode.risk==="medium"?"bg-amber-100 text-amber-700":"bg-gray-100 text-gray-600"}`}>{selectedNode.risk?.toUpperCase()??""}</span>
                </div>
                <p className="text-sm font-bold text-gray-900">{selectedNode.label}</p>
                <p className="text-[10px] font-mono text-gray-400 mt-0.5">{selectedNode.id}</p>
              </div>
              <button onClick={()=>setSelected(null)} className="text-gray-300 hover:text-gray-600 text-lg leading-none">×</button>
            </div>
            {connectedEdges.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Relationships ({connectedEdges.length})</p>
                <div className="space-y-1">
                  {connectedEdges.map((e,i)=>{
                    const isOut = e.source===selected;
                    const otherId = isOut ? e.target : e.source;
                    const other = nodeById[otherId];
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs bg-gray-50 rounded px-2 py-1">
                        <span className={`font-mono text-[10px] ${isOut?"text-blue-600":"text-purple-600"}`}>{isOut?"→":"←"}</span>
                        <span className="text-gray-500 italic">{e.label.replace(/_/g," ")}</span>
                        <span className="font-medium text-gray-800">{other?.label ?? otherId}</span>
                        {other&&<span className="text-[10px] text-gray-400">({other.type})</span>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // Email subject + body derived from selected node (or domain overview)
  const emailSubject = selectedNode
    ? `Action Required: ${selectedNode.label} (${selectedNode.type}) — ${domainName}`
    : `Knowledge Graph Review Request — ${domainName}`;
  const emailBody = selectedNode
    ? `Hi,\n\nPlease review the following entity in the ${domainName} Knowledge Graph:\n\nEntity: ${selectedNode.label}\nType: ${selectedNode.type}\nRisk: ${selectedNode.risk?.toUpperCase() ?? "INFO"}\nConnections: ${connectedEdges.length}\n\n${connectedEdges.length > 0 ? "Relationships:\n" + connectedEdges.map(e => `  ${e.source === selected ? "→" : "←"} ${e.label.replace(/_/g," ")}: ${e.source === selected ? e.target : e.source}`).join("\n") + "\n\n" : ""}Please take appropriate action.\n\nThank you`
    : `Hi,\n\nPlease review the ${domainName} Knowledge Graph (${graph.nodes.length} entities, ${graph.edges.length} relationships).\n\nPlease take appropriate action.\n\nThank you`;

  function copyEmail() {
    const body = (document.getElementById("kg-email-body") as HTMLTextAreaElement)?.value || emailBody;
    navigator.clipboard.writeText(`To: ${emailTo}\nSubject: ${emailSubject}\n\n${body}`).then(() => {
      setEmailCopied(true); setTimeout(() => setEmailCopied(false), 2000);
    });
  }

  function openEmailModal() {
    setGmailThreads([]);
    setEmailOpen(true);
    // Search Gmail for related threads after a brief delay
    const searchTerm = selectedNode ? selectedNode.label : domainName;
    if (!searchTerm) return;
    setGmailLoading(true);
    fetch(`/api/docintel/gmail-search?q=${encodeURIComponent(searchTerm)}&max_results=5`)
      .then(r => r.ok ? r.json() : { threads: [] })
      .then(d => { setGmailThreads(d.threads || []); })
      .catch(() => {})
      .finally(() => setGmailLoading(false));
  }

  // ── Graph View ───────────────────────────────────────────────────────────────
  return (
    <>
    {/* Email modal */}
    {emailOpen && (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/30" onClick={() => setEmailOpen(false)} />
        <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-2xl mx-4 p-6 flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between flex-shrink-0">
            <h3 className="text-base font-bold text-gray-800">Request Action / Send Email</h3>
            <button onClick={() => setEmailOpen(false)} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
          </div>

          {/* Entity context badge */}
          {selectedNode && (
            <div className="flex items-center gap-2 bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2 text-xs flex-shrink-0">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0"
                style={{ backgroundColor: nodeColor[selectedNode.type] ?? nodeColor.default }}>
                {selectedNode.type.slice(0,2).toUpperCase()}
              </div>
              <span className="font-semibold text-indigo-800">{selectedNode.label}</span>
              <span className="text-indigo-500">·</span>
              <span className="text-indigo-600">{selectedNode.type}</span>
            </div>
          )}

          <div className="flex gap-4">
            {/* Left: Compose form */}
            <div className="flex-1 space-y-3 min-w-0">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">To</label>
                <input
                  type="email"
                  placeholder="recipient@company.com"
                  value={emailTo}
                  onChange={e => setEmailTo(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Subject</label>
                <input type="text" value={emailSubject} readOnly
                  className="w-full border border-gray-100 rounded-lg px-3 py-2 text-sm bg-gray-50 text-gray-600" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Message</label>
                <textarea rows={8} defaultValue={emailBody} id="kg-email-body"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none" />
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`mailto:${encodeURIComponent(emailTo)}?subject=${encodeURIComponent(emailSubject)}&body=${encodeURIComponent((document.getElementById("kg-email-body") as HTMLTextAreaElement)?.value || emailBody)}`}
                  className="flex-1 text-center text-sm font-semibold px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
                >
                  Open in Mail App
                </a>
                <button onClick={copyEmail}
                  className="text-sm font-semibold px-4 py-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-gray-700">
                  {emailCopied ? "✓ Copied" : "Copy"}
                </button>
              </div>
            </div>

            {/* Right: Related Gmail threads */}
            <div className="w-60 flex-shrink-0 border-l border-gray-100 pl-4">
              <div className="flex items-center gap-1.5 mb-2">
                <svg className="w-3.5 h-3.5 text-red-500 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/>
                </svg>
                <span className="text-xs font-bold text-gray-700">Gmail Threads</span>
              </div>
              {gmailLoading ? (
                <div className="space-y-2">
                  {[1,2,3].map(i => (
                    <div key={i} className="animate-pulse rounded-lg bg-gray-100 h-16" />
                  ))}
                </div>
              ) : gmailThreads.length === 0 ? (
                <div className="text-xs text-gray-400 italic mt-2">
                  No related Gmail threads found.
                </div>
              ) : (
                <div className="space-y-2 overflow-y-auto max-h-64">
                  {gmailThreads.map((t, i) => (
                    <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 hover:bg-white hover:border-gray-200 transition-colors p-2.5 cursor-default">
                      <p className="text-[11px] font-semibold text-gray-800 truncate" title={t.subject}>{t.subject}</p>
                      {t.from && <p className="text-[10px] text-gray-500 truncate">{t.from}</p>}
                      {t.date && <p className="text-[10px] text-gray-400">{t.date}</p>}
                      {t.snippet && <p className="text-[10px] text-gray-600 mt-1 line-clamp-2">{t.snippet}</p>}
                    </div>
                  ))}
                </div>
              )}
              <p className="text-[10px] text-gray-400 mt-3 leading-tight">
                Searching Gmail for: <span className="italic">{selectedNode?.label ?? domainName}</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    )}

    <div className="flex gap-4">
      {/* SVG graph — light background */}
      <div className="flex-1 rounded-xl bg-white border border-gray-200 overflow-hidden" style={{ minHeight: 520 }}>

        {/* Search + zoom controls */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
          {/* Search bar */}
          <div className="relative flex-1 max-w-xs">
            <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search entities…"
              value={graphSearch}
              onChange={e => { setGraphSearch(e.target.value); setSelected(null); }}
              className="w-full pl-7 pr-7 py-1 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 bg-gray-50"
            />
            {graphSearch && (
              <button onClick={() => setGraphSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 leading-none text-sm">×</button>
            )}
          </div>
          {graphSearch && (
            <span className="text-[10px] text-blue-600 font-semibold whitespace-nowrap">
              {visibleNodeIds?.size ?? 0} match{(visibleNodeIds?.size ?? 0) !== 1 ? "es" : ""}
            </span>
          )}
          <div className="h-4 w-px bg-gray-200 mx-1" />
          <span className="text-[10px] text-gray-400">Zoom</span>
          <button
            onClick={() => setZoom(z => Math.min(4, z + 0.2))}
            className="w-6 h-6 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 text-sm font-bold leading-none flex items-center justify-center"
            title="Zoom in">+</button>
          <button
            onClick={() => setZoom(z => Math.max(0.3, z - 0.2))}
            className="w-6 h-6 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 text-sm font-bold leading-none flex items-center justify-center"
            title="Zoom out">−</button>
          <button
            onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
            className="px-2 h-6 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 text-[10px] font-semibold"
            title="Reset view">Reset</button>
          <span className="text-[10px] text-gray-400 ml-1">{Math.round(zoom * 100)}%</span>
          <span className="text-[10px] text-gray-300 ml-2 hidden lg:block">Scroll to zoom · Drag to pan · Click node to inspect</span>
          <div className="ml-auto">
            <button
              onClick={openEmailModal}
              title="Send email / request action"
              className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-md border border-gray-200 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors text-gray-500 cursor-pointer bg-white"
            >
              <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              <span className="hidden sm:inline">Request Action</span>
            </button>
          </div>
        </div>

        <div
          className="overflow-hidden"
          style={{ cursor: dragging ? "grabbing" : "grab", height: 520 }}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            viewBox={`0 0 ${W} ${H}`}
            style={{ userSelect: "none" }}
          >
            <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
              <defs>
                {presentTypes.map(type => {
                  const c = nodeColor[type] ?? nodeColor.default;
                  return (
                    <marker key={type} id={`arr-${type}`} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                      <path d="M0,0 L0,6 L8,3 z" fill={c} />
                    </marker>
                  );
                })}
                <marker id="arr-sel" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L8,3 z" fill="#6366f1" />
                </marker>
                <marker id="arr-default" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L8,3 z" fill="#94a3b8" />
                </marker>
              </defs>

              {/* Edges */}
              {graph.edges.map((e, i) => {
                const s = nodeById[e.source], t = nodeById[e.target];
                if (!s || !t) return null;
                const isSel  = !!(selected && (e.source === selected || e.target === selected));
                const isHov  = !selected && (hovered === e.source || hovered === e.target);
                const isEHov = hoveredEdge === i;
                const highlight = isSel || isHov || isEHov;
                const srcColor  = nodeColor[s.type] ?? nodeColor.default;
                const dimmed    = !!(selected && !isSel);
                const d = edgePath(s.x, s.y, t.x, t.y);
                const dx = t.x - s.x, dy = t.y - s.y;
                const cx = s.x + dx * 0.5 + (dy !== 0 ? dy * 0.15 : 40);
                const cy = s.y + dy * 0.5 - (dx !== 0 ? dx * 0.1 : 0);
                const lx = 0.25 * s.x + 0.5 * cx + 0.25 * t.x;
                const ly = 0.25 * s.y + 0.5 * cy + 0.25 * t.y;
                return (
                  <g key={i} opacity={dimmed ? 0.08 : 1}
                    onMouseEnter={() => setHoveredEdge(i)}
                    onMouseLeave={() => setHoveredEdge(null)}>
                    <path d={d} fill="none" stroke="transparent" strokeWidth={12} style={{ cursor: "pointer" }} />
                    <path
                      d={d} fill="none"
                      stroke={isSel ? "#6366f1" : isHov || isEHov ? srcColor : "#94a3b8"}
                      strokeWidth={isSel ? 2.5 : isHov || isEHov ? 2 : 1.2}
                      markerEnd={isSel ? "url(#arr-sel)" : isHov || isEHov ? `url(#arr-${s.type})` : "url(#arr-default)"}
                      opacity={highlight ? 1 : 0.6}
                    />
                    {(highlight || graph.edges.length < 20) && (
                      <text x={lx} y={ly - 5} textAnchor="middle" fontSize={isEHov ? 10 : 8}
                        fill={isSel ? "#6366f1" : isEHov ? "#1e293b" : "#64748b"}
                        fontWeight={isEHov ? "700" : "400"}
                        className="pointer-events-none">
                        {e.label.replace(/_/g," ")}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Nodes */}
              {graph.nodes.map(n => {
                const color  = nodeColor[n.type] ?? nodeColor.default;
                const isHov  = hovered === n.id;
                const isSel  = selected === n.id;
                const degree = connCount[n.id] ?? 0;
                const r      = isSel ? 28 : isHov ? 26 : Math.min(22, 16 + degree * 1.5);
                const searchDimmed = !!(visibleNodeIds && !visibleNodeIds.has(n.id));
                const dimmed = searchDimmed || !!(selected && !isSel && !connectedEdges.some(e => e.source === n.id || e.target === n.id));
                return (
                  <g key={n.id} style={{ cursor: "pointer" }} opacity={dimmed ? 0.15 : 1}
                    onClick={() => handleNodeClick(n.id)}
                    onMouseEnter={() => setHovered(n.id)}
                    onMouseLeave={() => setHovered(null)}>
                    {(n.risk === "critical" || n.risk === "high") && !dimmed && (
                      <circle cx={n.x} cy={n.y} r={r + 8} fill={color} opacity={0.12} />
                    )}
                    {isSel && <circle cx={n.x} cy={n.y} r={r + 6} fill="none" stroke="#6366f1" strokeWidth={2} strokeDasharray="4,3" opacity={0.8} />}
                    {isHov && !isSel && <circle cx={n.x} cy={n.y} r={r + 4} fill="none" stroke={color} strokeWidth={1.5} opacity={0.4} />}
                    <circle cx={n.x} cy={n.y} r={r}
                      fill={isSel ? "#6366f1" : color}
                      stroke={isSel ? "#4f46e5" : isHov ? "#1e293b" : "rgba(0,0,0,0.15)"}
                      strokeWidth={isSel ? 2.5 : isHov ? 1.5 : 1}
                    />
                    <text x={n.x} y={n.y + 1} textAnchor="middle" dominantBaseline="middle"
                      fontSize={r > 20 ? 11 : 9} fontWeight="bold" fill="white" className="pointer-events-none">
                      {n.type.slice(0,2).toUpperCase()}
                    </text>
                    <text x={n.x} y={n.y + r + 13} textAnchor="middle"
                      fontSize={isSel || isHov ? 10 : 9}
                      fill={isSel ? "#4f46e5" : isHov ? "#0f172a" : "#374151"}
                      fontWeight={isSel || isHov ? "700" : "500"}
                      className="pointer-events-none">
                      {n.label.length > 16 ? n.label.slice(0, 15) + "…" : n.label}
                    </text>
                    <text x={n.x} y={n.y + r + 23} textAnchor="middle"
                      fontSize={7.5} fill="#6b7280" className="pointer-events-none">
                      {n.type}
                    </text>
                    {degree > 0 && !dimmed && (
                      <text x={n.x + r - 2} y={n.y - r + 4} textAnchor="middle" dominantBaseline="middle"
                        fontSize={7} fill="white" fontWeight="bold" className="pointer-events-none">
                        {degree}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 px-3 py-2.5 border-t border-gray-100">
          {presentTypes.map(type => (
            <div key={type} className="flex items-center gap-1.5 text-[11px] text-gray-500">
              <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: nodeColor[type] ?? nodeColor.default }} />
              {type}
            </div>
          ))}
        </div>
      </div>

      {/* Detail panel — light theme */}
      {selectedNode && (
        <div className="w-64 flex-shrink-0 bg-white rounded-xl border border-indigo-200 shadow-lg p-4 self-start sticky top-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">Entity Detail</p>
            <button onClick={() => setSelected(null)} className="text-gray-300 hover:text-gray-700 text-xl leading-none" title="Close">×</button>
          </div>

          <div className="flex items-center gap-2 mb-3">
            <div className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
              style={{ backgroundColor: nodeColor[selectedNode.type] ?? nodeColor.default }}>
              {selectedNode.type.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900 leading-tight">{selectedNode.label}</p>
              <p className="text-[10px] text-gray-500">{selectedNode.type}</p>
            </div>
          </div>

          <div className="space-y-1.5 text-xs mb-4">
            <div className="flex justify-between">
              <span className="text-gray-500">ID</span>
              <span className="font-mono text-gray-600 text-[10px] truncate max-w-36">{selectedNode.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Risk</span>
              <span className={`font-bold px-1.5 py-0.5 rounded text-[10px] ${selectedNode.risk === "critical" ? "bg-red-100 text-red-700" : selectedNode.risk === "high" ? "bg-orange-100 text-orange-700" : selectedNode.risk === "medium" ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-600"}`}>
                {selectedNode.risk?.toUpperCase() ?? "INFO"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Connections</span>
              <span className="font-bold text-gray-900">{connectedEdges.length}</span>
            </div>
          </div>

          {connectedEdges.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Relationships ({connectedEdges.length})
              </p>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {connectedEdges.map((e, i) => {
                  const isOut   = e.source === selected;
                  const otherId = isOut ? e.target : e.source;
                  const other   = nodeById[otherId];
                  const otherColor = nodeColor[other?.type ?? ""] ?? nodeColor.default;
                  return (
                    <div key={i}
                      className="text-[10px] bg-gray-50 rounded px-2.5 py-2 border border-gray-200 cursor-pointer hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
                      onClick={() => setSelected(otherId)}>
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className={`font-mono font-bold text-xs ${isOut ? "text-blue-600" : "text-purple-600"}`}>{isOut ? "→" : "←"}</span>
                        <span className="italic text-gray-500">{e.label.replace(/_/g," ")}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: otherColor }} />
                        <p className="font-semibold text-gray-800">{other?.label ?? otherId}</p>
                      </div>
                      {other && <p className="text-gray-400 mt-0.5">{other.type}</p>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Email / Request Action button */}
          <button
            onClick={openEmailModal}
            className="mt-4 w-full flex items-center justify-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-gray-200 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors text-gray-600 cursor-pointer"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            Request Action / Send Email
          </button>
        </div>
      )}

      {/* Email button when no node selected */}
      {!selectedNode && (
        <div className="flex-shrink-0 self-start mt-2">
          <button
            onClick={openEmailModal}
            title="Send email / request action"
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-gray-200 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors text-gray-500 cursor-pointer bg-white"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            Send Email
          </button>
        </div>
      )}
    </div>
    </>
  );
}

// ── Action Center ─────────────────────────────────────────────────────────────

function ActionCard({ pb, onLogged, domainId = "supply_chain", incidentRef = "RCL-2024-0012", sourceDocs = [], onDocClick, apiBase = "" }: { pb: Playbook; onLogged: () => void; domainId?: string; incidentRef?: string; sourceDocs?: ActionDocRef[]; onDocClick?: (docId: string) => void; apiBase?: string }) {
  const [expanded, setExpanded] = useState(false);
  const [loggedBy, setLoggedBy] = useState(pb.default_logged_by);
  const [desc, setDesc] = useState(pb.description);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [actionMasterId, setActionMasterId] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string>("OPEN");

  async function takeAction() {
    setSubmitting(true);
    try {
      // Write to legacy action_log (backward compat)
      await postJson(`/api/docintel/log-action?domain_id=${encodeURIComponent(domainId)}`, {
        action_type: pb.action_type,
        description: desc,
        priority: pb.priority,
        incident_ref: incidentRef,
        logged_by: loggedBy,
      });
      // Also write to platform.action_master for lifecycle tracking
      try {
        const res = await fetch(`${apiBase}/api/docintel/action-master`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            domain_id:    domainId,
            action_type:  pb.action_type,
            description:  desc,
            priority:     pb.priority,
            incident_ref: incidentRef,
            logged_by:    loggedBy,
          }),
        });
        if (res.ok) {
          const r = await res.json();
          setActionMasterId(r.action_id);
          setActionStatus("OPEN");
        }
      } catch { /* lifecycle tracking optional */ }
      setDone(true);
      setExpanded(false);
      onLogged();
    } catch { } finally { setSubmitting(false); }
  }

  return (
    <div className={`rounded-lg border bg-white transition-all ${expanded?"border-indigo-300 ring-1 ring-indigo-200":"border-gray-200 hover:border-gray-300"}`}>
      <div className="p-4">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${prioColor[pb.priority]}`}>{pb.priority}</span>
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${CAT_COLOR[pb.category]??""}`}>{pb.category}</span>
              {done && !actionMasterId && <span className="text-[10px] font-bold text-green-700 bg-green-50 px-1.5 py-0.5 rounded">✓ Logged</span>}
              {actionMasterId && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${ACTION_STATUS_COLORS[actionStatus] ?? ACTION_STATUS_COLORS.OPEN}`}>
                  {actionStatus.replace(/_/g," ")}
                </span>
              )}
            </div>
            <h3 className="text-sm font-semibold text-gray-900 leading-snug">{pb.name}</h3>
          </div>
          <button
            onClick={() => setExpanded(e => !e)}
            className={`flex-shrink-0 text-xs font-semibold px-3 py-1.5 rounded-md transition-colors ${expanded?"bg-gray-100 text-gray-700":"bg-indigo-600 text-white hover:bg-indigo-700"}`}
          >
            {expanded ? "Cancel" : "Take Action"}
          </button>
        </div>

        <p className="text-xs text-gray-600 leading-relaxed">{pb.description}</p>

        {/* What it does + next steps */}
        <div className="mt-2.5 space-y-1.5 text-xs">
          <p className="text-gray-500"><span className="font-medium text-gray-700">What this does:</span> {pb.what_it_does}</p>
          <div className="text-gray-500">
            <span className="font-medium text-gray-700">Next steps:</span>
            <ol className="list-decimal list-inside mt-0.5 space-y-0.5 pl-2">
              {pb.next_steps.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
          </div>
        </div>

        {/* Source documents from the Library */}
        {sourceDocs.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
              📄 Relevant Documents in Library
            </p>
            <div className="flex flex-wrap gap-1.5">
              {sourceDocs.map(doc => (
                <button
                  key={doc.doc_id}
                  onClick={() => onDocClick?.(doc.doc_id)}
                  title={`${doc.doc_type} · ${doc.processed_ts ? new Date(doc.processed_ts).toLocaleDateString() : ""}`}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-[10px] font-medium hover:bg-blue-100 hover:border-blue-400 transition-colors cursor-pointer max-w-[180px]"
                >
                  <span className="truncate">{doc.filename || doc.doc_id}</span>
                  <span className="text-blue-400 flex-shrink-0">↗</span>
                </button>
              ))}
            </div>
            <p className="text-[9px] text-gray-400 mt-1">Click any document to review it in the Library</p>
          </div>
        )}
      </div>

      {/* Expanded action form */}
      {expanded && (
        <div className="border-t border-indigo-100 bg-indigo-50 p-4 space-y-3 rounded-b-lg">
          <p className="text-xs font-semibold text-indigo-800">Confirm &amp; Log Action</p>
          <div>
            <label className="block text-[10px] font-medium text-gray-600 mb-1">Description (edit if needed)</label>
            <textarea
              value={desc} onChange={e=>setDesc(e.target.value)} rows={3}
              className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 resize-none bg-white"
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <label className="block text-[10px] font-medium text-gray-600 mb-1">Logged by</label>
              <input value={loggedBy} onChange={e=>setLoggedBy(e.target.value)}
                className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 bg-white" />
            </div>
            <div>
              <label className="block text-[10px] font-medium text-gray-600 mb-1">Priority</label>
              <span className={`inline-block text-[10px] font-bold px-2 py-1.5 rounded ${prioColor[pb.priority]}`}>{pb.priority}</span>
            </div>
            <div>
              <label className="block text-[10px] font-medium text-gray-600 mb-1">Incident</label>
              <span className="inline-block text-[10px] font-mono bg-gray-100 px-2 py-1.5 rounded text-gray-700">{incidentRef}</span>
            </div>
          </div>
          <button
            onClick={takeAction} disabled={submitting||!desc.trim()}
            className="w-full py-2 text-xs font-bold bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Logging action…" : `Confirm: ${pb.name}`}
          </button>
        </div>
      )}
    </div>
  );
}

function ActionCenter({ catFilter, onLogged, actions, domainId = "supply_chain", incidentRef = "", onDocClick, apiBase = "" }: { catFilter: string; onLogged: () => void; actions: ActionEntry[]; domainId?: string; incidentRef?: string; onDocClick?: (docId: string) => void; apiBase?: string }) {
  const [reportLoading, setReportLoading] = useState(false);
  const [reportText, setReportText] = useState<string|null>(null);
  const [docsByType, setDocsByType] = useState<Record<string, ActionDocRef[]>>({});
  // Action Master tracker
  const [masterActions, setMasterActions] = useState<ActionMasterRecord[]>([]);
  const [masterLoading, setMasterLoading] = useState(false);

  const loadMasterActions = useCallback(() => {
    if (!domainId) return;
    setMasterLoading(true);
    fetch(`${apiBase}/api/docintel/action-master?domain_id=${encodeURIComponent(domainId)}`)
      .then(r => r.ok ? r.json() : { actions: [] })
      .then(d => setMasterActions(d.actions ?? []))
      .catch(() => {})
      .finally(() => setMasterLoading(false));
  }, [domainId, apiBase]);

  useEffect(() => { loadMasterActions(); }, [loadMasterActions]);

  // Reports sub-tab
  if (catFilter === "reports") {
    return <ActionReportsView domainId={domainId} apiBase={apiBase} />;
  }

  const domainPlaybooks = getDomainPlaybooks(domainId);
  const filtered = catFilter==="all"
    ? domainPlaybooks
    : domainPlaybooks.filter(p=>p.category.toLowerCase()===catFilter);

  // Collect all unique doc types needed by visible playbooks and fetch them once
  useEffect(() => {
    const allTypes = Array.from(new Set(domainPlaybooks.flatMap(p => p.source_doc_types ?? [])));
    if (!allTypes.length) return;
    fetch(`/api/docintel/docs-by-type?domain_id=${encodeURIComponent(domainId)}&doc_types=${encodeURIComponent(allTypes.join(","))}`)
      .then(r => r.ok ? r.json() : { by_type: {} })
      .then(d => setDocsByType(d.by_type ?? {}))
      .catch(() => {});
  }, [domainId]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCount = actions.filter(a=>a.status==="OPEN").length;
  const critCount = actions.filter(a=>a.priority==="CRITICAL"||a.priority==="HIGH").length;

  async function generateReport() {
    setReportLoading(true);
    try {
      const data = await fetchJson(`/api/docintel/action-report?incident_ref=${encodeURIComponent(incidentRef)}&domain_id=${encodeURIComponent(domainId)}`);
      setReportText(data.report_markdown ?? "");
    } catch (e: any) { setReportText(`Error: ${e.message}`); }
    finally { setReportLoading(false); }
  }

  return (
    <div className="space-y-5">
      {/* Summary */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="text-xs text-gray-500">
          Showing <strong className="text-gray-800">{filtered.length}</strong> action{filtered.length!==1?"s":""}
          {incidentRef && <> · Ref: <span className="font-mono font-semibold text-red-700">{incidentRef}</span></>}
        </div>
        <div className="flex gap-2 ml-auto">
          {openCount>0&&<span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">{openCount} open logged</span>}
          {critCount>0&&<span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-red-100 text-red-700 animate-pulse">{critCount} require action</span>}
        </div>
      </div>

      {/* Playbook grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map(pb => {
          // Collect all docs whose type matches any of this card's source_doc_types
          const cardDocs = (pb.source_doc_types ?? []).flatMap(t => docsByType[t] ?? []);
          // Deduplicate by doc_id
          const seen = new Set<string>();
          const uniqueDocs = cardDocs.filter(d => { if (seen.has(d.doc_id)) return false; seen.add(d.doc_id); return true; });
          return (
            <ActionCard key={pb.id} pb={pb} onLogged={onLogged} domainId={domainId} incidentRef={incidentRef}
              sourceDocs={uniqueDocs} onDocClick={onDocClick} apiBase={apiBase} />
          );
        })}
      </div>

      {/* Action Master — lifecycle tracker */}
      {masterActions.length > 0 && (
        <div className="border-t border-gray-200 pt-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">Active Action Tracker</h3>
            <button onClick={loadMasterActions} className="text-[11px] text-gray-500 hover:text-gray-800 border border-gray-200 px-2.5 py-1 rounded-md">↺ Refresh</button>
          </div>
          <div className="space-y-2">
            {masterActions.map(a => (
              <ActionLifecycleRow key={a.action_id} action={a} apiBase={apiBase} onRefresh={loadMasterActions} />
            ))}
          </div>
        </div>
      )}

      {/* History section */}
      {actions.length > 0 && (
        <div className="border-t border-gray-200 pt-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">Logged Actions History</h3>
            <div className="flex gap-2">
              <button onClick={generateReport} disabled={reportLoading}
                className="text-xs font-medium px-3 py-1.5 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
                {reportLoading ? "Generating…" : "Generate Report"}
              </button>
            </div>
          </div>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {actions.map((a, i) => {
              const needsAction = a.status==="OPEN" && (a.priority==="CRITICAL"||a.priority==="HIGH");
              return (
                <div key={i} className={`rounded-md border p-2.5 text-xs ${needsAction?"border-red-200 bg-red-50":"border-gray-100 bg-white"}`}>
                  <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
                    <span className={`px-1.5 py-0.5 rounded font-semibold text-[10px] ${prioColor[a.priority]??prioColor.MEDIUM}`}>{a.priority}</span>
                    <span className="font-medium text-gray-700">{a.action_type.replace(/_/g," ")}</span>
                    {needsAction&&<span className="text-[10px] font-bold text-red-600 animate-pulse ml-auto">⚠ OPEN</span>}
                  </div>
                  <p className="text-gray-600">{a.description}</p>
                  <div className="flex gap-3 mt-1 text-[10px] text-gray-400">
                    <span>📅 {fmtDate(String(a.logged_at))}</span>
                    <span>👤 {a.logged_by}</span>
                    <span>#{a.action_id}</span>
                  </div>
                </div>
              );
            })}
          </div>
          {reportText && (
            <div className="mt-4 rounded-md bg-gray-50 border border-gray-200 p-4 max-h-80 overflow-y-auto">
              <pre className="text-[11px] text-gray-700 leading-relaxed whitespace-pre-wrap font-mono">{reportText}</pre>
              <button
                onClick={()=>{const b=new Blob([reportText],{type:"text/markdown"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=`incident-report-${incidentRef}.md`;a.click();}}
                className="mt-2 text-xs text-indigo-600 hover:text-indigo-800 underline">
                ↓ Download as Markdown
              </button>
            </div>
          )}
        </div>
      )}

      {/* Custom action form */}
      <CustomActionForm onLogged={onLogged} domainId={domainId} incidentRef={incidentRef} />
    </div>
  );
}

const ACTION_TYPES = ["RECALL_NOTIFICATION","SUPPLIER_CONTACT","PRODUCT_HOLD","INSPECTION","REGULATORY_FILING","MEDIA_STATEMENT","DISTRIBUTION_CENTER_ALERT","RESTAURANT_NOTIFICATION","FINANCIAL_CLAIM","ROOT_CAUSE_ANALYSIS","CORRECTIVE_ACTION","CLOSEOUT"];

function CustomActionForm({ onLogged, domainId = "supply_chain", incidentRef = "RCL-2024-0012" }: { onLogged: () => void; domainId?: string; incidentRef?: string }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ action_type: ACTION_TYPES[0], description: "", priority: "MEDIUM", logged_by: "" });
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.description.trim()) return;
    setSubmitting(true);
    try {
      await postJson(`/api/docintel/log-action?domain_id=${encodeURIComponent(domainId)}`, { ...form, incident_ref: incidentRef });
      setForm(f=>({...f, description:""}));
      setOpen(false);
      onLogged();
    } catch {} finally { setSubmitting(false); }
  }

  return (
    <div className="border border-dashed border-gray-300 rounded-lg">
      <button onClick={()=>setOpen(o=>!o)} className="w-full flex items-center gap-2 px-4 py-3 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-50 rounded-lg transition-colors">
        <span className="text-base">+</span>
        <span className="font-medium">Log a Custom Action</span>
        <span className="ml-auto text-gray-400">Not covered by playbooks above? Log it here.</span>
      </button>
      {open && (
        <form onSubmit={submit} className="border-t border-gray-200 p-4 space-y-2.5">
          <div className="flex gap-2">
            <select value={form.action_type} onChange={e=>setForm(f=>({...f,action_type:e.target.value}))}
              className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
              {ACTION_TYPES.map(t=><option key={t} value={t}>{t.replace(/_/g," ")}</option>)}
            </select>
            <select value={form.priority} onChange={e=>setForm(f=>({...f,priority:e.target.value}))}
              className="w-28 text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
              {["CRITICAL","HIGH","MEDIUM","LOW"].map(p=><option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <textarea value={form.description} onChange={e=>setForm(f=>({...f,description:e.target.value}))}
            placeholder="Describe the action taken or required…" rows={2}
            className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 resize-none"/>
          <div className="flex gap-2">
            <input value={form.logged_by} onChange={e=>setForm(f=>({...f,logged_by:e.target.value}))}
              placeholder="Your name / role" className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5"/>
            <button type="submit" disabled={submitting||!form.description.trim()}
              className="px-4 text-xs font-semibold bg-gray-800 text-white rounded-md hover:bg-gray-900 disabled:opacity-50">
              {submitting?"Logging…":"Log Action"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

// ── Action Lifecycle System ────────────────────────────────────────────────────

const ACTION_STATUS_COLORS: Record<string, string> = {
  OPEN:                 "bg-gray-100 text-gray-700 border-gray-300",
  INITIATED:            "bg-blue-100 text-blue-700 border-blue-300",
  IN_PROGRESS:          "bg-amber-100 text-amber-700 border-amber-300",
  PENDING_VERIFICATION: "bg-purple-100 text-purple-700 border-purple-300",
  COMPLETED:            "bg-green-100 text-green-700 border-green-300",
  IGNORED:              "bg-gray-100 text-gray-500 border-gray-200",
  CANCELLED:            "bg-red-50 text-red-400 border-red-200",
};

interface ActionMasterRecord {
  action_id: string; domain_id: string; action_type: string; description: string;
  priority: string; status: string; owner?: string; due_date?: string; eta?: string;
  next_update_date?: string; completed_date?: string; verified_by?: string;
  ignore_reason?: string; cancel_reason?: string; logged_by?: string;
  created_at?: string; updated_at?: string; incident_ref?: string; source_doc_ids?: string;
}

/** Modal dialog for collecting transition-specific fields */
function TransitionModal({ title, fields, onConfirm, onCancel, submitting }: {
  title: string;
  fields: { key: string; label: string; type?: string; required?: boolean }[];
  onConfirm: (values: Record<string, string>) => void;
  onCancel: () => void;
  submitting: boolean;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onCancel} />
      <div className="relative bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-md mx-4 p-6 space-y-4">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        {fields.map(f => (
          <div key={f.key}>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {f.label}{f.required && <span className="text-red-500 ml-0.5">*</span>}
            </label>
            {f.type === "textarea" ? (
              <textarea rows={3} value={vals[f.key] ?? ""} onChange={e => setVals(v => ({ ...v, [f.key]: e.target.value }))}
                className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400" />
            ) : (
              <input type={f.type ?? "text"} value={vals[f.key] ?? ""} onChange={e => setVals(v => ({ ...v, [f.key]: e.target.value }))}
                className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" />
            )}
          </div>
        ))}
        <div className="flex gap-2 pt-2">
          <button disabled={submitting} onClick={() => onConfirm(vals)}
            className="flex-1 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
            {submitting ? "Saving…" : "Confirm"}
          </button>
          <button onClick={onCancel} className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

/** Inline lifecycle badge + transition buttons for an action_master record */
function ActionLifecycleRow({ action, apiBase, onRefresh }: {
  action: ActionMasterRecord; apiBase: string; onRefresh: () => void;
}) {
  const [modal, setModal] = useState<string | null>(null);  // transition key
  const [submitting, setSubmitting] = useState(false);
  const [histOpen, setHistOpen] = useState(false);
  const [history, setHistory] = useState<{old_status:string;new_status:string;changed_by:string;changed_at:string;comments:string}[]>([]);

  const TRANSITION_CONFIG: Record<string, {
    label: string; color: string;
    fields: { key: string; label: string; type?: string; required?: boolean }[];
  }> = {
    INITIATED: {
      label: "Initiate",
      color: "bg-blue-600 text-white hover:bg-blue-700",
      fields: [
        { key: "owner",    label: "Assign Owner",  required: true },
        { key: "due_date", label: "Due Date",       type: "date", required: true },
        { key: "changed_by", label: "Your name",   required: true },
      ],
    },
    IN_PROGRESS: {
      label: "Start Work",
      color: "bg-amber-500 text-white hover:bg-amber-600",
      fields: [
        { key: "eta",              label: "ETA (Date)",             type: "date" },
        { key: "next_update_date", label: "Next Update Date",       type: "date" },
        { key: "changed_by",       label: "Your name",              required: true },
      ],
    },
    PENDING_VERIFICATION: {
      label: "Submit for Review",
      color: "bg-purple-600 text-white hover:bg-purple-700",
      fields: [
        { key: "changed_by", label: "Your name", required: true },
        { key: "comments",   label: "Notes",     type: "textarea" },
      ],
    },
    COMPLETED: {
      label: "Mark Completed",
      color: "bg-green-600 text-white hover:bg-green-700",
      fields: [
        { key: "verified_by", label: "Verified by", required: true },
        { key: "changed_by",  label: "Your name",   required: true },
      ],
    },
    IGNORED: {
      label: "Ignore",
      color: "border border-gray-300 text-gray-600 hover:bg-gray-50",
      fields: [
        { key: "ignore_reason", label: "Reason for ignoring", type: "textarea", required: true },
        { key: "ignore_by",     label: "Your name",           required: true },
        { key: "changed_by",    label: "Your name",           required: true },
      ],
    },
    CANCELLED: {
      label: "Cancel",
      color: "border border-red-200 text-red-600 hover:bg-red-50",
      fields: [
        { key: "cancel_reason",       label: "Reason for cancellation", type: "textarea", required: true },
        { key: "cancel_authorized_by", label: "Authorized by",          required: true },
        { key: "changed_by",          label: "Your name",               required: true },
      ],
    },
  };

  const STATUS_TRANSITIONS: Record<string, string[]> = {
    OPEN:                 ["INITIATED", "IGNORED"],
    INITIATED:            ["IN_PROGRESS", "CANCELLED"],
    IN_PROGRESS:          ["PENDING_VERIFICATION", "CANCELLED"],
    PENDING_VERIFICATION: ["COMPLETED", "IN_PROGRESS"],
  };

  const allowedTransitions = STATUS_TRANSITIONS[action.status] ?? [];

  async function doTransition(newStatus: string, vals: Record<string, string>) {
    setSubmitting(true);
    try {
      await fetch(`${apiBase}/api/docintel/action-master/${action.action_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          new_status:          newStatus,
          changed_by:          vals.changed_by ?? "app_user",
          comments:            vals.comments ?? "",
          owner:               vals.owner,
          due_date:            vals.due_date,
          eta:                 vals.eta,
          next_update_date:    vals.next_update_date,
          verified_by:         vals.verified_by,
          ignore_reason:       vals.ignore_reason,
          ignore_by:           vals.ignore_by,
          cancel_reason:       vals.cancel_reason,
          cancel_authorized_by: vals.cancel_authorized_by,
        }),
      });
      setModal(null);
      onRefresh();
    } catch (e: any) {
      alert("Update failed: " + e.message);
    } finally {
      setSubmitting(false); }
  }

  async function loadHistory() {
    if (histOpen) { setHistOpen(false); return; }
    const d = await fetch(`${apiBase}/api/docintel/action-master/${action.action_id}/history`).then(r => r.json()).catch(() => ({ history: [] }));
    setHistory(d.history ?? []);
    setHistOpen(true);
  }

  const statusColor = ACTION_STATUS_COLORS[action.status] ?? ACTION_STATUS_COLORS.OPEN;

  return (
    <div className={`rounded-lg border p-3.5 bg-white text-xs space-y-2 ${["COMPLETED","CANCELLED","IGNORED"].includes(action.status) ? "opacity-60" : ""}`}>
      <div className="flex items-start gap-2 flex-wrap">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${ACTION_STATUS_COLORS[action.priority] ?? prioColor.MEDIUM}`}>{action.priority}</span>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${statusColor}`}>{action.status.replace(/_/g, " ")}</span>
        <span className="font-medium text-gray-800 flex-1">{action.action_type.replace(/_/g, " ")}</span>
        <span className="text-gray-400 font-mono text-[10px]">#{action.action_id}</span>
      </div>
      <p className="text-gray-600 leading-relaxed">{action.description}</p>
      <div className="flex flex-wrap gap-3 text-[10px] text-gray-400">
        {action.owner     && <span>👤 {action.owner}</span>}
        {action.due_date  && <span>📅 Due {action.due_date}</span>}
        {action.eta       && <span>⏱ ETA {action.eta}</span>}
        {action.logged_by && <span>🖊 {action.logged_by}</span>}
        {action.created_at && <span>{new Date(action.created_at).toLocaleDateString()}</span>}
      </div>
      {allowedTransitions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {allowedTransitions.map(t => {
            const cfg = TRANSITION_CONFIG[t];
            if (!cfg) return null;
            return (
              <button key={t} onClick={() => setModal(t)}
                className={`text-[11px] font-semibold px-2.5 py-1 rounded-md ${cfg.color}`}>
                {cfg.label}
              </button>
            );
          })}
          <button onClick={loadHistory}
            className="text-[11px] px-2.5 py-1 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 ml-auto">
            {histOpen ? "Hide History" : "History"}
          </button>
        </div>
      )}
      {histOpen && history.length > 0 && (
        <div className="border-t border-gray-100 pt-2 space-y-1 max-h-40 overflow-y-auto">
          {history.map((h, i) => (
            <div key={i} className="flex gap-2 text-[10px] text-gray-500">
              <span className="text-gray-300">{h.changed_at?.slice(0,16)}</span>
              <span className="font-mono">{h.old_status || "—"} → {h.new_status}</span>
              <span>by {h.changed_by}</span>
              {h.comments && <span className="text-gray-400">· {h.comments}</span>}
            </div>
          ))}
        </div>
      )}
      {/* Transition modal */}
      {modal && TRANSITION_CONFIG[modal] && (
        <TransitionModal
          title={`${TRANSITION_CONFIG[modal].label}: ${action.action_type.replace(/_/g," ")}`}
          fields={TRANSITION_CONFIG[modal].fields}
          submitting={submitting}
          onCancel={() => setModal(null)}
          onConfirm={(vals) => doTransition(modal, vals)}
        />
      )}
    </div>
  );
}

/** Action Reports sub-tab */
function ActionReportsView({ domainId, apiBase }: { domainId: string; apiBase: string }) {
  const [data, setData]     = useState<{by_status:Record<string,number>;by_priority:Record<string,number>;total:number;overdue:ActionMasterRecord[];actions:ActionMasterRecord[];overdue_count:number} | null>(null);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState("ALL");
  const [histExpanded, setHistExpanded] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    fetch(`${apiBase}/api/docintel/action-reports?domain_id=${encodeURIComponent(domainId)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };
  useEffect(load, [domainId]); // eslint-disable-line

  const STATUS_ORDER = ["OPEN","INITIATED","IN_PROGRESS","PENDING_VERIFICATION","COMPLETED","IGNORED","CANCELLED"];

  if (loading) return <div className="text-center text-sm text-gray-400 py-10">Loading action reports…</div>;
  if (!data) return <div className="text-center text-sm text-gray-400 py-10">No action data yet.</div>;

  const filtered = filterStatus === "ALL" ? data.actions : data.actions.filter(a => a.status === filterStatus);

  return (
    <div className="space-y-5">
      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Actions",  val: data.total,                 color: "bg-gray-50 border-gray-200 text-gray-800" },
          { label: "Open / Active",  val: (data.by_status["OPEN"] ?? 0) + (data.by_status["INITIATED"] ?? 0) + (data.by_status["IN_PROGRESS"] ?? 0) + (data.by_status["PENDING_VERIFICATION"] ?? 0), color: "bg-blue-50 border-blue-200 text-blue-800" },
          { label: "Completed",      val: data.by_status["COMPLETED"] ?? 0, color: "bg-green-50 border-green-200 text-green-800" },
          { label: "Overdue",        val: data.overdue_count,         color: data.overdue_count > 0 ? "bg-red-50 border-red-200 text-red-800" : "bg-gray-50 border-gray-200 text-gray-800" },
        ].map(k => (
          <div key={k.label} className={`rounded-lg border px-4 py-3 ${k.color}`}>
            <p className="text-2xl font-bold">{k.val}</p>
            <p className="text-xs font-medium">{k.label}</p>
          </div>
        ))}
      </div>

      {/* Status distribution */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {STATUS_ORDER.filter(s => data.by_status[s]).map(s => (
          <div key={s} className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border ${ACTION_STATUS_COLORS[s] ?? "bg-gray-50 border-gray-200 text-gray-700"}`}>
            <span className="font-semibold">{data.by_status[s]}</span>
            <span>{s.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>

      {/* Overdue actions */}
      {data.overdue.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-2">
          <p className="text-xs font-semibold text-red-700">⚠️ {data.overdue.length} Overdue Actions</p>
          {data.overdue.map(a => (
            <div key={a.action_id} className="text-xs text-red-800 flex gap-2 items-start">
              <span className="font-mono font-semibold">{a.action_id}</span>
              <span className="flex-1">{a.description}</span>
              <span className="font-semibold text-red-600">Due {a.due_date}</span>
            </div>
          ))}
        </div>
      )}

      {/* Refresh + filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-semibold text-gray-600">All Actions</p>
        <div className="flex gap-1 ml-auto flex-wrap">
          {["ALL", ...STATUS_ORDER].filter(s => s === "ALL" || data.by_status[s]).map(s => (
            <button key={s} onClick={() => setFilterStatus(s)}
              className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${filterStatus === s ? "bg-gray-800 text-white border-gray-800" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
              {s === "ALL" ? "All" : s.replace(/_/g, " ")}
            </button>
          ))}
          <button onClick={load} className="text-[11px] px-2.5 py-1 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 ml-1">↺ Refresh</button>
        </div>
      </div>

      {/* Action table */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <div className="grid grid-cols-12 bg-gray-50 border-b border-gray-200 px-3 py-2 text-[10px] font-bold text-gray-500 uppercase tracking-wide">
          <span className="col-span-2">ID / Type</span>
          <span className="col-span-4">Description</span>
          <span className="col-span-2">Status</span>
          <span className="col-span-2">Priority / Owner</span>
          <span className="col-span-2">Date / Due</span>
        </div>
        <div className="divide-y divide-gray-100 max-h-[480px] overflow-y-auto">
          {filtered.length === 0 && (
            <div className="text-center text-xs text-gray-400 py-8">No actions matching this filter.</div>
          )}
          {filtered.map(a => (
            <div key={a.action_id}>
              <div className="grid grid-cols-12 px-3 py-2.5 text-xs hover:bg-gray-50 cursor-pointer"
                onClick={() => setHistExpanded(h => h === a.action_id ? null : a.action_id)}>
                <div className="col-span-2">
                  <p className="font-mono text-[10px] text-gray-500">{a.action_id}</p>
                  <p className="text-gray-700 font-medium truncate">{a.action_type.replace(/_/g," ")}</p>
                </div>
                <div className="col-span-4 pr-2">
                  <p className="text-gray-600 line-clamp-2">{a.description}</p>
                </div>
                <div className="col-span-2">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${ACTION_STATUS_COLORS[a.status] ?? ""}`}>
                    {a.status.replace(/_/g," ")}
                  </span>
                </div>
                <div className="col-span-2 space-y-0.5">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${prioColor[a.priority] ?? prioColor.MEDIUM}`}>{a.priority}</span>
                  {a.owner && <p className="text-gray-500 text-[10px]">👤 {a.owner}</p>}
                </div>
                <div className="col-span-2 text-[10px] text-gray-400 space-y-0.5">
                  {a.created_at && <p>{new Date(a.created_at).toLocaleDateString()}</p>}
                  {a.due_date   && <p className={a.due_date < new Date().toISOString().slice(0,10) && !["COMPLETED","CANCELLED"].includes(a.status) ? "text-red-500 font-semibold" : ""}>{a.due_date}</p>}
                  {a.completed_date && <p className="text-green-600">✓ {a.completed_date?.slice(0,10)}</p>}
                </div>
              </div>
              {/* History expansion */}
              {histExpanded === a.action_id && (
                <ActionHistoryInline actionId={a.action_id} apiBase={apiBase} />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ActionHistoryInline({ actionId, apiBase }: { actionId: string; apiBase: string }) {
  const [history, setHistory] = useState<{old_status:string;new_status:string;changed_by:string;changed_at:string;comments:string}[]>([]);
  useEffect(() => {
    fetch(`${apiBase}/api/docintel/action-master/${actionId}/history`).then(r => r.json()).then(d => setHistory(d.history ?? [])).catch(() => {});
  }, [actionId]); // eslint-disable-line
  return (
    <div className="col-span-12 px-4 pb-3 bg-gray-50 border-t border-gray-100 text-[11px] text-gray-500 space-y-1">
      <p className="font-semibold text-gray-600 pt-2">History</p>
      {history.length === 0 && <p className="text-gray-400">No history yet.</p>}
      {history.map((h, i) => (
        <div key={i} className="flex gap-3">
          <span className="text-gray-300 font-mono">{h.changed_at?.slice(0,16)}</span>
          <span className="font-medium">{h.old_status || "—"} → {h.new_status}</span>
          <span>by <strong>{h.changed_by}</strong></span>
          {h.comments && <span className="text-gray-400">· {h.comments}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Severity colours ──────────────────────────────────────────────────────────
const SEV_COLOR: Record<string,string> = {
  critical: "bg-red-100 text-red-800 border-red-300",
  high:     "bg-orange-100 text-orange-800 border-orange-300",
  medium:   "bg-amber-100 text-amber-800 border-amber-300",
  low:      "bg-gray-100 text-gray-700 border-gray-200",
};
const STATUS_ICON: Record<string,string> = {
  active: "🔴", investigating: "🟡", resolved: "✅", escalated: "⚠️",
};

interface IncidentSummary {
  incident_id: string; incident_type: string; title: string;
  status: string; severity: string; opened_date: string;
  primary_entity_label: string; financial_exposure_usd: number;
  affected_count: number; affected_label: string;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SupplyChainPage({ domain: domainProp }: { domain?: import("@/context/DomainContext").DomainInfo }) {
  const { domain: domainCtx } = useDomain();
  const domain = domainProp ?? domainCtx;
  const domainId = domain?.domain_id || "supply_chain";
  const domainName = domain?.name || domainId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const isSupplyChain = domainId === "supply_chain";
  const domainParam = `domain_id=${encodeURIComponent(domainId)}`;
  const TABS = buildTabs(domainId);

  // ── Incident selector ──
  const [incidents,        setIncidents]        = useState<IncidentSummary[]>([]);
  const [activeIncidentId, setActiveIncidentId] = useState<string>("");
  // Incident detail drawer
  const [incidentDetail,   setIncidentDetail]   = useState<Record<string,unknown>|null>(null);
  const [detailOpen,       setDetailOpen]       = useState(false);
  const [detailLoading,    setDetailLoading]    = useState(false);

  // ── Document viewer panel ──
  const [viewDocId,     setViewDocId]     = useState<string | null>(null);
  const openDocViewer  = (docId: string)  => setViewDocId(docId);
  const closeDocViewer = ()               => setViewDocId(null);

  // ── Generic domain overview (non-supply-chain) ──
  const [domainOverview, setDomainOverview] = useState<DomainOverview|null>(null);

  const activeIncident = incidents.find(i => i.incident_id === activeIncidentId) ?? null;

  useEffect(() => {
    fetchJson(`/api/docintel/incidents?${domainParam}`)
      .then(d => {
        const list: IncidentSummary[] = d.incidents ?? [];
        setIncidents(list);
        // default to first active/critical incident
        const first = list.find(i => i.status === "active") ?? list[0];
        if (first) setActiveIncidentId(first.incident_id);
      })
      .catch(() => {});
  }, [domainParam]);

  const [ontGraph,  setOntGraph]  = useState<OntGraph|null>(null);
  const [actions,   setActions]   = useState<ActionEntry[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string|null>(null);

  // Two-level nav: tab + sub — reset when domain changes
  const [tab, setTab]   = useState<string>("overview");
  const [sub, setSub]   = useState<string>("summary");

  // Overview accordion sections (expanded by default)
  const [accDocTypes,   setAccDocTypes]   = useState(true);
  const [accEntities,   setAccEntities]   = useState(true);
  const [accExtractions, setAccExtractions] = useState(true);

  // Reset sub-tab when domain switches
  useEffect(() => {
    setSub("summary");
    setTab("overview");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domainId]);
  const [pageLoadedAt]  = useState(()=>new Date().toLocaleString("en-US",{month:"short",day:"numeric",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"}));

  const loadActions = useCallback(async () => {
    try {
      const incRef = activeIncidentId ? `&incident_ref=${encodeURIComponent(activeIncidentId)}` : "";
      const data = await fetchJson(`/api/docintel/action-log?${domainParam}${incRef}`);
      setActions(data.actions ?? []);
    } catch { setActions([]); }
  }, [domainParam, activeIncidentId]);

  const openIncidentDetail = useCallback(async (id: string) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setIncidentDetail(null);
    try {
      const data = await fetchJson(`/api/docintel/incidents/${encodeURIComponent(id)}?${domainParam}`);
      setIncidentDetail(data);
    } catch { setIncidentDetail({ error: "Could not load incident details." }); }
    finally { setDetailLoading(false); }
  }, [domainParam]);

  useEffect(()=>{
    setLoading(true);
    Promise.all([
      fetchJson(`/api/docintel/domain-overview?${domainParam}`),
      fetchJson(`/api/docintel/ontology-graph?${domainParam}`),
    ])
      .then(([ov, og])=>{ setDomainOverview(ov); setOntGraph(og); })
      .catch(e=>setError(e.message))
      .finally(()=>setLoading(false));
    loadActions();
  }, [loadActions, domainParam]);

  function switchTab(tabId: string) {
    setTab(tabId);
    const t = TABS.find(t=>t.id===tabId);
    if (t && t.subs.length > 0) setSub(t.subs[0].id);
  }

  const currentTab = TABS.find(t=>t.id===tab) ?? TABS[0];
  const openActions = actions.filter(a=>a.status==="OPEN").length;

  return (
    <>
    <main className="min-h-screen bg-gray-50">

      {/* ── Incident detail drawer ── */}
      {detailOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/30" onClick={() => setDetailOpen(false)} />
          {/* Panel */}
          <div className="relative w-full max-w-md bg-white h-full shadow-2xl flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <p className="text-sm font-bold text-gray-900">{activeIncidentId}</p>
                <p className="text-[10px] text-gray-400">Incident Details</p>
              </div>
              <button onClick={() => setDetailOpen(false)} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">×</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {detailLoading && <p className="text-sm text-gray-400 animate-pulse">Loading…</p>}
              {incidentDetail && !detailLoading && (() => {
                const inc = incidentDetail as Record<string, unknown>;
                const docs = (inc.linked_documents ?? []) as Array<Record<string, unknown>>;
                const hasError = !!inc.error;
                if (hasError) return <p className="text-sm text-red-500">{String(inc.error)}</p>;
                return (
                  <div className="space-y-5">
                    {/* Header details */}
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { l: "Type",     v: String(inc.incident_type ?? "") },
                        { l: "Status",   v: String(inc.status ?? "") },
                        { l: "Severity", v: String(inc.severity ?? "") },
                        { l: "Opened",   v: String(inc.opened_date ?? "") },
                        { l: "Primary Entity", v: String(inc.primary_entity_label ?? "") },
                        { l: "Exposure", v: typeof inc.financial_exposure_usd === "number" ? fmt(inc.financial_exposure_usd as number) : "—" as string },
                        { l: "Affected", v: `${inc.affected_count ?? "—"} ${inc.affected_label ?? ""}` },
                      ].map(({ l, v }) => (
                        <div key={l} className="bg-gray-50 rounded-lg px-3 py-2">
                          <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide">{l}</p>
                          <p className="text-xs font-semibold text-gray-800 mt-0.5 leading-snug">{v}</p>
                        </div>
                      ))}
                    </div>

                    {/* Description */}
                    {inc.description && (
                      <div>
                        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Description</p>
                        <p className="text-xs text-gray-700 leading-relaxed bg-gray-50 rounded-lg p-3">{String(inc.description)}</p>
                      </div>
                    )}

                    {/* Linked documents */}
                    <div>
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
                        Evidence Documents ({docs.length})
                      </p>
                      {docs.length === 0
                        ? <p className="text-xs text-gray-400 italic">No documents linked to this incident.</p>
                        : <div className="space-y-2">
                            {docs.map((d, i) => {
                              const name = String(d.filename ?? d.document_name ?? d.document_path ?? d.doc_id ?? "");
                              const docType = String(d.doc_type_label ?? d.doc_type ?? "");
                              const preview = d.text_preview ? String(d.text_preview) : null;
                              const words = d.est_word_count ? Number(d.est_word_count) : null;
                              return (
                                <div key={i} className="bg-gray-50 rounded-lg border border-gray-100 px-3 py-2.5">
                                  <div className="flex items-start gap-2">
                                    <span className="text-base flex-shrink-0 mt-0.5">📄</span>
                                    <div className="min-w-0 flex-1">
                                      <p className="text-xs font-semibold text-gray-800 break-words leading-snug">{name}</p>
                                      <div className="flex items-center gap-2 mt-0.5">
                                        {docType && (
                                          <span className="text-[9px] font-semibold bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">
                                            {docType.replace(/_/g, " ")}
                                          </span>
                                        )}
                                        {words && (
                                          <span className="text-[10px] text-gray-400">~{words.toLocaleString()} words</span>
                                        )}
                                        {d.linked_at && (
                                          <span className="text-[9px] text-gray-300">linked {String(d.linked_at).slice(0,10)}</span>
                                        )}
                                      </div>
                                      {preview && (
                                        <p className="text-[10px] text-gray-500 mt-1 leading-relaxed line-clamp-2 italic">
                                          {preview}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                      }
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab navigation header ── */}
      <header className="bg-white border-b border-gray-200">
        {/* Compact title row */}
        <div className="px-6 pt-3 pb-0 flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-700">{domainName} Control Tower</span>
        </div>

        {/* ── Level 1: Primary tabs (always visible, with tooltips) ── */}
        <div className="px-8 flex gap-1 border-b border-gray-100">
          {TABS.map(t => {
            const isActive = tab === t.id;
            const badgeCount = t.id === "actions" ? openActions : 0;
            return (
              <button
                key={t.id}
                title={t.tooltip}
                onClick={() => switchTab(t.id)}
                className={`relative group flex items-center gap-1.5 px-4 py-3 text-sm font-semibold border-b-2 transition-colors ${
                  isActive
                    ? "border-blue-600 text-blue-700 bg-blue-50/50"
                    : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
                }`}
              >
                <span>{t.icon}</span>
                <span>{t.label}</span>
                {badgeCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 w-4 h-4 text-[9px] font-bold bg-red-500 text-white rounded-full flex items-center justify-center">
                    {badgeCount}
                  </span>
                )}
                {/* Tooltip bubble */}
                <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 leading-relaxed opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg text-left">
                  <strong className="block mb-0.5">{t.label}</strong>
                  {t.tooltip}
                </span>
              </button>
            );
          })}
        </div>

        {/* ── Level 2: Sub-tabs (change with primary tab) ── */}
        <div className="px-8 py-2 flex gap-1 flex-wrap bg-gray-50">
          {currentTab.subs.map(s => (
            <button
              key={s.id}
              onClick={() => setSub(s.id)}
              className={`px-3 py-1 text-xs rounded-md transition-colors font-medium ${
                sub === s.id
                  ? "bg-white border border-blue-200 text-blue-700 shadow-sm"
                  : "text-gray-500 hover:text-gray-800 hover:bg-white hover:border hover:border-gray-200"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div className="m-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          <strong>Error loading data:</strong> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-center text-gray-500">
            <div className="text-2xl mb-2 animate-spin">⟳</div>
            <p>Loading {domainName} intelligence…</p>
          </div>
        </div>
      ) : (
        <div className="p-6 max-w-7xl mx-auto">

          {/* ── OVERVIEW TAB ── */}
          {tab === "overview" && (
            <div className="space-y-4">

              {/* KPI Cards */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {[
                  { label:"Documents Processed",     value: domainOverview?.total_docs ?? "—",            color:"text-blue-600"   },
                  { label:"Document Types",           value: domainOverview?.doc_types.length ?? "—",      color:"text-indigo-600" },
                  { label:"Knowledge Graph Entities", value: domainOverview?.total_entities ?? "—",        color:"text-purple-600" },
                ].map(kpi => (
                  <div key={kpi.label} className="bg-white rounded-lg border border-gray-200 p-4 text-center">
                    <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
                    <p className="text-xs text-gray-500 mt-1">{kpi.label}</p>
                  </div>
                ))}
              </div>

              {/* Accordion: Document Types */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <button
                  onClick={() => setAccDocTypes(v => !v)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-semibold text-gray-800 hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  <span>Document Types</span>
                  <span className="flex items-center gap-2 text-xs text-gray-400 font-normal">
                    {domainOverview?.total_docs ?? 0} docs · <code className="bg-gray-100 px-1 rounded">{domain?.schema_raw ?? domainId}.parsed_documents</code>
                    <svg className={`w-4 h-4 transition-transform ${accDocTypes ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </span>
                </button>
                {accDocTypes && (
                  <div className="px-5 pb-5 border-t border-gray-100">
                    {domainOverview && domainOverview.doc_types.length > 0 ? (
                      <div className="space-y-2 pt-4">
                        {domainOverview.doc_types.map((dt, i) => {
                          const pct = domainOverview.total_docs > 0 ? Math.round(dt.doc_count / domainOverview.total_docs * 100) : 0;
                          const colors = ["bg-blue-500","bg-indigo-500","bg-purple-500","bg-pink-500","bg-rose-500","bg-orange-500","bg-amber-500","bg-teal-500"];
                          return (
                            <div key={i} className="flex items-center gap-3 text-xs">
                              <span className="w-44 truncate text-gray-700 font-medium">{dt.doc_type?.replace(/_/g," ")}</span>
                              <div className="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
                                <div className={`h-full rounded-full ${colors[i % colors.length]}`} style={{width:`${pct}%`}}/>
                              </div>
                              <span className="w-10 text-right font-mono text-gray-500">{dt.doc_count}</span>
                              <span className="w-8 text-right text-gray-400">{pct}%</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-gray-400 text-center py-6">No documents processed yet. Run the pipeline to classify documents.</p>
                    )}
                  </div>
                )}
              </div>

              {/* Accordion: Entity Distribution */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <button
                  onClick={() => setAccEntities(v => !v)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-semibold text-gray-800 hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  <span>Entity Distribution</span>
                  <span className="flex items-center gap-2 text-xs text-gray-400 font-normal">
                    {domainOverview?.total_entities ?? 0} entities · {domainOverview?.total_relationships ?? 0} relationships
                    <svg className={`w-4 h-4 transition-transform ${accEntities ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </span>
                </button>
                {accEntities && (
                  <div className="px-5 pb-5 border-t border-gray-100">
                    {domainOverview && domainOverview.entity_types.length > 0 ? (
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 pt-4">
                        {domainOverview.entity_types.map((et, i) => {
                          const colors = ["text-blue-600 bg-blue-50 border-blue-100","text-indigo-600 bg-indigo-50 border-indigo-100","text-purple-600 bg-purple-50 border-purple-100","text-pink-600 bg-pink-50 border-pink-100","text-teal-600 bg-teal-50 border-teal-100","text-orange-600 bg-orange-50 border-orange-100"];
                          return (
                            <div key={i} className={`rounded-lg border px-4 py-3 ${colors[i % colors.length]}`}>
                              <p className="text-lg font-bold">{et.count}</p>
                              <p className="text-xs font-medium">{et.entity_type}</p>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-gray-400 text-center py-6">No entities indexed yet. Run the pipeline to build the knowledge graph.</p>
                    )}
                  </div>
                )}
              </div>

              {/* Accordion: Key Extractions */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <button
                  onClick={() => setAccExtractions(v => !v)}
                  className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-semibold text-gray-800 hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  <span>Key Extractions</span>
                  <span className="flex items-center gap-2 text-xs text-gray-400 font-normal">
                    Sample of AI-extracted fields
                    <svg className={`w-4 h-4 transition-transform ${accExtractions ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </span>
                </button>
                {accExtractions && (
                  <div className="px-5 pb-5 border-t border-gray-100">
                    {domainOverview && domainOverview.recent_extractions.length > 0 ? (
                      <div className="overflow-auto max-h-96 pt-4">
                        <table className="w-full text-xs">
                          <thead><tr className="border-b border-gray-100 text-left">
                            <th className="py-2 text-gray-500 pr-3">Document</th>
                            <th className="py-2 text-gray-500 pr-3">Type</th>
                            <th className="py-2 text-gray-500 pr-3">Field</th>
                            <th className="py-2 text-gray-500">Value</th>
                          </tr></thead>
                          <tbody>
                            {domainOverview.recent_extractions.map((ex, i) => (
                              <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                                <td className="py-1.5 pr-3 font-mono text-gray-500 text-[10px] max-w-[120px] truncate">{ex.doc_id?.replace(/\.pdf$/i,"")}</td>
                                <td className="py-1.5 pr-3 text-indigo-600">{ex.doc_type?.replace(/_/g," ")}</td>
                                <td className="py-1.5 pr-3 font-semibold text-gray-700">{ex.field_name?.replace(/_/g," ")}</td>
                                <td className="py-1.5 text-gray-600 max-w-xs truncate">{ex.field_value}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-xs text-gray-400 text-center py-6">No extracted fields yet. Run the pipeline to extract structured data from documents.</p>
                    )}
                  </div>
                )}
              </div>

            </div>
          )}


          {/* ── ONTOLOGY TAB ── */}
          {tab === "ontology" && (
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-800">{domainName} Knowledge Graph</h2>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {ontGraph?.nodes.length??0} entities · {ontGraph?.edges.length??0} relationships ·{" "}
                    {ontGraph?.source==="live"?"Live from Unity Catalog":"Incident graph (ontology tables empty)"}
                  </p>
                </div>
                {ontGraph?.source==="fallback"&&(
                  <span className="text-xs px-2 py-1 bg-amber-50 border border-amber-200 text-amber-700 rounded-full">Fallback graph</span>
                )}
              </div>
              {ontGraph ? <OntologyMap graph={ontGraph} sub={sub} domainName={domainName}/> : <p className="text-sm text-gray-400">Loading…</p>}
            </div>
          )}

          {/* ── ACTION CENTER TAB ── */}
          {tab === "actions" && (
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <div className="mb-5">
                  <h2 className="text-base font-semibold text-gray-800">Action Center — {domainName}</h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  {getDomainPlaybooks(domainId).length} predefined response actions across {getDomainCategories(domainId).length - 1} categories ·
                  All actions logged with timestamp to <code className="bg-gray-100 px-1 rounded">jai_docintel.agents.action_log</code>
                </p>
              </div>
              <ActionCenter
                catFilter={sub}
                onLogged={loadActions}
                actions={actions}
                domainId={domainId}
                incidentRef={activeIncidentId}
                onDocClick={openDocViewer}
                apiBase={getApiBaseUrl()}
              />
            </div>
          )}

          {/* ── COMPLIANCE MAP TAB ── */}
          {tab === "compliance_map" && (
            <ComplianceMapTab domainId={domainId} sub={sub} apiBase={getApiBaseUrl()} />
          )}

          {/* ── COPILOT STUDIO TAB ── */}
          {tab === "copilot" && (
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <CopilotStudio
                domainId={domainId}
                sub={sub}
                apiBase={getApiBaseUrl()}
                onSwitchToSetup={() => setSub("setup")}
              />
            </div>
          )}

          <p className="text-xs text-center text-gray-400 pb-4 mt-8">
            Domain: <code>{domainId}</code> · jai_docintel catalog ·
            Powered by Databricks AI Functions + Foundation Model APIs
          </p>
        </div>
      )}
    </main>

    {/* ── Global Document Viewer Panel ── */}
    {viewDocId && (
      <DocViewerPanel
        docId={viewDocId}
        domainId={domainId}
        onClose={closeDocViewer}
      />
    )}
    </>
  );
}
