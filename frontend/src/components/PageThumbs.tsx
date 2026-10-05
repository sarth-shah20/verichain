import { useState } from "react";
import type { DocumentResult } from "@/api/types";

/** Per-page heatmap thumbnails with a page picker. */
export function PageThumbs({
  doc,
  onSelect,
}: {
  doc: DocumentResult;
  onSelect: (url: string) => void;
}) {
  const pages = doc.pipeline1.heatmap_pages ?? [];
  const [active, setActive] = useState(0);
  if (pages.length <= 1) return null;
  return (
    <div className="flex gap-2 overflow-x-auto">
      {pages.map((p, i) => (
        <button
          key={p.page_number}
          onClick={() => {
            setActive(i);
            if (p.url) onSelect(p.url);
          }}
          className={`shrink-0 overflow-hidden rounded-lg border ${i === active ? "border-pipeline1" : "border-slate-700"}`}
          title={`Page ${p.page_number}`}
        >
          <img src={p.url ?? undefined} alt={`Page ${p.page_number}`} className="h-20 w-16 object-cover" />
        </button>
      ))}
    </div>
  );
}
