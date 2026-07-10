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

interface DomainContextValue {
  domain: DomainInfo;
  setDomain: (d: DomainInfo) => void;
}

const DEFAULT_DOMAIN: DomainInfo = {
  domain_id: "supply_chain",
  name: "Supply Chain",
  description: "QSR supply chain document intelligence",
  status: "active",
  schema_ready: false,
};

export const DomainContext = createContext<DomainContextValue>({
  domain: DEFAULT_DOMAIN,
  setDomain: () => {},
});

export function useDomain(): DomainContextValue {
  return useContext(DomainContext);
}
