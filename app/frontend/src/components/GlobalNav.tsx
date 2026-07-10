"use client";

import Link from "next/link";
import Image from "next/image";

export function GlobalNav() {
  return (
    <nav className="w-full bg-white border-b border-gray-200 shadow-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-3 flex items-center h-9 gap-3">
        {/* Databricks logo — compact, clicking returns to Subject Area selector */}
        <Link href="/" title="Home — Subject Area selector" className="flex-shrink-0">
          <Image src="/Databricks_Logo.png" alt="Databricks" width={72} height={22} className="h-5 w-auto" priority />
        </Link>

        {/* Divider */}
        <span className="h-4 border-l border-gray-200" />

        {/* App name — larger, prominent */}
        <Link href="/" className="text-base font-bold text-gray-800 tracking-tight leading-none">
          DocIntelligence
        </Link>

        {/* Right side — workspace badge */}
        <div className="ml-auto hidden md:flex items-center gap-1 text-[10px] text-gray-400 flex-shrink-0 font-mono">
          <span>jai_docintel</span>
          <span className="text-gray-300">·</span>
          <span>jai-az-ws</span>
        </div>
      </div>
    </nav>
  );
}
