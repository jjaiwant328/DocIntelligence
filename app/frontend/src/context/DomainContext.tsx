"use client";

import React, { createContext, useContext } from "react";

export interface DomainInfo {
  domain_id: string;
  name: string;
  description?: string;
  status?: string;
  schema_raw?: string;
  schema_ont?: string;
  doc_count?: number;
  analytics_config?: string;
  suggested_questions?: string;
  /** True once the user has saved a domain schema (classification labels etc.) */
  schema_ready?: boolean;
}

/** A project/case within a subject area (from platform.projects). */
export interface ProjectInfo {
  project_id: string;
  name?: string;
  municipality?: string;
  state?: string;
  status?: string;
  owner?: string;
  collaborators?: string[];
}

interface DomainContextValue {
  domain: DomainInfo;
  setDomain: (d: DomainInfo) => void;
  /** The active project/case, scoping Skills / Workflows / Executions. */
  project: ProjectInfo | null;
  setProject: (p: ProjectInfo | null) => void;
  /** Demo identity: the user we are "acting as" and whether access is enforced. */
  actingUser: string;
  setActingUser: (u: string) => void;
  enforceAccess: boolean;
  setEnforceAccess: (v: boolean) => void;
}

const DEFAULT_DOMAIN: DomainInfo = {
  domain_id: "supply_chain",
  name: "Supply Chain",
  description: "QSR supply chain document intelligence",
  status: "active",
  schema_ready: false,
};

/** Demo users to "act as" — pure app-level identity, not Databricks auth. */
export const DEMO_USERS = ["Alex Chen", "Jordan Smith", "Sam Rivera", "Taylor Kim"];

export const DomainContext = createContext<DomainContextValue>({
  domain: DEFAULT_DOMAIN,
  setDomain: () => {},
  project: null,
  setProject: () => {},
  actingUser: DEMO_USERS[0],
  setActingUser: () => {},
  enforceAccess: false,
  setEnforceAccess: () => {},
});

export function useDomain(): DomainContextValue {
  return useContext(DomainContext);
}
