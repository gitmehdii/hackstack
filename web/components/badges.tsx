// Petits composants de présentation partagés (source, classement, techno).

const SOURCE_LABELS: Record<string, string> = {
  lablab: "lablab.ai",
  devpost: "Devpost",
  ethglobal: "ETHGlobal",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-neutral-300 dark:border-neutral-700 px-2 py-0.5 text-xs text-neutral-600 dark:text-neutral-300">
      {sourceLabel(source)}
    </span>
  );
}

export function PlacementBadge({
  placement,
  isWinner,
}: {
  placement: number | null;
  isWinner: boolean;
}) {
  if (placement === null && !isWinner) {
    return null;
  }
  const label =
    placement === 1
      ? "🥇 1ᵉʳ"
      : placement === 2
        ? "🥈 2ᵉ"
        : placement === 3
          ? "🥉 3ᵉ"
          : placement !== null
            ? `#${placement}`
            : "Gagnant";
  return (
    <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-300 px-2 py-0.5 text-xs font-medium">
      {label}
    </span>
  );
}

export function TechChips({ items }: { items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t) => (
        <span
          key={t}
          className="inline-flex items-center rounded bg-neutral-200/70 dark:bg-neutral-800 px-1.5 py-0.5 text-xs text-neutral-700 dark:text-neutral-300"
        >
          {t}
        </span>
      ))}
    </div>
  );
}
