import type { ReactNode } from "react";

import type { ModelListing, ModelSummary } from "@/lib/api";
import { shortDirectory } from "@/lib/models";

/** The line along the bottom: the model in view and its stats, then the directory and how many models it holds. */
export function StatusBar({
  listing,
  model,
  stats,
}: {
  listing: ModelListing | null;
  model: ModelSummary | null;
  stats?: ReactNode;
}) {
  const count = listing?.models.length ?? 0;
  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 overflow-hidden border-t border-line bg-panel px-3 mono-annotation whitespace-nowrap text-ink-muted">
      {model && <span className="truncate text-ink">{model.name}</span>}
      {stats}
      <span className="flex-1" />
      {listing && (
        <>
          <span title={listing.directory} className="truncate">
            {shortDirectory(listing.directory)}
          </span>
          <span>
            {count} {count === 1 ? "model" : "models"}
          </span>
        </>
      )}
    </footer>
  );
}
