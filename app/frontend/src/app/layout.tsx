import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { GlobalNav } from "@/components/GlobalNav";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "DocIntelligence — Multi-Domain Document AI",
  description: "Multi-domain document intelligence powered by Databricks AI Functions, Foundation Model APIs, Unity Catalog, and Databricks AI Agents.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={cn(
        "min-h-screen bg-background font-sans antialiased",
        inter.className
      )}>
        <GlobalNav />
        {children}
      </body>
    </html>
  );
}
