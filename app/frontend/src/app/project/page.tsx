"use client";

import { useState } from "react";
import { useDomain } from "@/context/DomainContext";
import type { DomainInfo } from "@/context/DomainContext";
import { InventoryPanel } from "@/components/InventoryPanel";
import { SearchPanel } from "@/components/SearchPanel";

type WorkspaceTab = "inventory" | "search";

const TABS: { id: WorkspaceTab; icon: string; label: string; desc: string }[] = [
  {
    id:    "inventory",
    icon:  "📋",
    label: "Inventory",
    desc:  "Browse and manage indexed documents for this project.",
  },
  {
    id:    "search",
    icon:  "🔍",
    label: "Search",
    desc:  "Hybrid vector + full-text search over all indexed content.",
  },
];

export default function ProjectPage({ domain }: { domain: DomainInfo }) {
  const { project }             = useDomain();
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("inventory");

  return (
    <div className="flex flex-col min-h-0 flex-1 bg-gray-50">
      {/* Persistent non-sensitive data banner */}
      <div className="flex items-center gap-2 px-6 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800 flex-shrink-0">
        <span className="flex-shrink-0">⚠️</span>
        <span>
          <strong>Non-sensitive documents only.</strong> This workspace is for
          non-confidential, non-PII content. Do not index personal data,
          credentials, or regulated records.
        </span>
      </div>

      {/* No-project guard */}
      {!project ? (
        <div className="flex-1 flex items-center justify-center py-24">
          <div className="text-center">
            <p className="text-base text-gray-600 mb-1">Select a project to continue.</p>
            <p className="text-sm text-gray-400">
              Use the project picker in the toolbar above.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col p-6 min-h-0">
          {/* Project header */}
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-base font-bold text-gray-900">
              {project.name ?? project.project_id}
            </h2>
            <span className="text-xs text-gray-400">in {domain.name}</span>
          </div>

          {/* Inner tab bar */}
          <div className="flex gap-0 border-b border-gray-200 mb-5">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                title={t.desc}
                className={`flex items-center gap-1.5 px-4 py-2 text-xs font-semibold border-b-2 transition-colors whitespace-nowrap cursor-pointer ${
                  activeTab === t.id
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
                }`}
              >
                <span>{t.icon}</span>
                <span>{t.label}</span>
              </button>
            ))}
          </div>

          {/* Panel */}
          {activeTab === "inventory" && (
            <InventoryPanel
              domainId={domain.domain_id}
              projectId={project.project_id}
            />
          )}
          {activeTab === "search" && (
            <SearchPanel
              domainId={domain.domain_id}
              projectId={project.project_id}
            />
          )}
        </div>
      )}
    </div>
  );
}
