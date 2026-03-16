"use client";

import { FileText, Download, Image, Table, FileSpreadsheet, Presentation } from "lucide-react";
import type { Artifact } from "@/lib/api";

interface ArtifactViewerProps {
  artifacts: Artifact[];
}

const FORMAT_CONFIG: Record<
  string,
  { icon: typeof FileText; color: string; bg: string }
> = {
  pdf: { icon: FileText, color: "text-accent-red", bg: "bg-accent-red/10" },
  pptx: { icon: Presentation, color: "text-accent-yellow", bg: "bg-accent-yellow/10" },
  docx: { icon: FileText, color: "text-accent-blue", bg: "bg-accent-blue/10" },
  xlsx: { icon: FileSpreadsheet, color: "text-accent-green", bg: "bg-accent-green/10" },
  png: { icon: Image, color: "text-accent-purple", bg: "bg-accent-purple/10" },
  jpg: { icon: Image, color: "text-accent-purple", bg: "bg-accent-purple/10" },
  csv: { icon: Table, color: "text-accent-green", bg: "bg-accent-green/10" },
};

export function ArtifactViewer({ artifacts }: ArtifactViewerProps) {
  if (!artifacts || artifacts.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider px-1">
        Generated Files
      </h3>
      <div className="grid grid-cols-1 gap-2">
        {artifacts.map((artifact, i) => (
          <ArtifactCard key={i} artifact={artifact} />
        ))}
      </div>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const format = artifact.format?.toLowerCase() || "pdf";
  const config = FORMAT_CONFIG[format] || FORMAT_CONFIG.pdf;
  const Icon = config.icon;

  const isImage = ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(format);

  const handleDownload = () => {
    if (artifact.content_b64) {
      const byteCharacters = atob(artifact.content_b64);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const blob = new Blob([new Uint8Array(byteNumbers)], { type: artifact.mime_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = artifact.name;
      a.click();
      URL.revokeObjectURL(url);
    } else if (artifact.url) {
      window.open(artifact.url, "_blank");
    }
  };

  const sizeKb = artifact.content_b64
    ? Math.round((artifact.content_b64.length * 3) / 4 / 1024)
    : null;

  return (
    <div className="rounded-xl border border-border bg-bg-card p-4 hover:border-border-hover transition-colors">
      {/* Image preview */}
      {isImage && artifact.content_b64 && (
        <div className="mb-3 rounded-lg overflow-hidden bg-bg-secondary">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:${artifact.mime_type};base64,${artifact.content_b64}`}
            alt={artifact.name}
            className="w-full h-auto max-h-48 object-contain"
          />
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg ${config.bg} flex items-center justify-center flex-shrink-0`}>
          <Icon className={`w-5 h-5 ${config.color}`} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-medium text-text-primary truncate">
            {artifact.name}
          </p>
          <p className="text-[11px] text-text-tertiary font-mono">
            {format.toUpperCase()}
            {sizeKb !== null && ` \u00B7 ${sizeKb} KB`}
          </p>
        </div>
        <button
          onClick={handleDownload}
          className="flex items-center gap-1.5 h-8 px-3 rounded-lg bg-bg-tertiary border border-border text-[12px] text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors flex-shrink-0"
        >
          <Download className="w-3.5 h-3.5" />
          Download
        </button>
      </div>
    </div>
  );
}
