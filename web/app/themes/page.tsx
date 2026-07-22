import type { Metadata } from "next";
import Link from "next/link";

import { getThemes } from "@/lib/api";

export const revalidate = 86400;

export const metadata: Metadata = {
  title: "Thèmes",
  description:
    "Les thèmes des projets de hackathon : volume, taux de victoire et stacks dominantes.",
};

export default async function ThemesPage() {
  const data = await getThemes();
  const themes = data?.themes ?? [];
  const withProjects = themes.filter((t) => t.project_count > 0);
  const empty = themes.filter((t) => t.project_count === 0);

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">Thèmes</h1>
        <p className="text-neutral-500">
          Taxonomie fermée de {themes.length} thèmes. Un projet en porte au plus trois.
        </p>
      </header>

      <ul className="grid sm:grid-cols-2 gap-3">
        {withProjects.map((t) => (
          <li key={t.slug}>
            <Link
              href={`/theme/${encodeURIComponent(t.slug)}`}
              className="block h-full rounded-lg border border-neutral-200 dark:border-neutral-800 px-4 py-3 hover:border-neutral-400 dark:hover:border-neutral-600"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">{t.label}</span>
                <span className="text-sm tabular-nums text-neutral-500">
                  {t.project_count.toLocaleString("fr")}
                </span>
              </div>
              <p className="mt-1 text-sm text-neutral-500 line-clamp-2">{t.description}</p>
            </Link>
          </li>
        ))}
      </ul>

      {empty.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-neutral-500">
            Thèmes sans projet pour l&apos;instant
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {empty.map((t) => (
              <span
                key={t.slug}
                className="inline-flex items-center rounded-full border border-neutral-200 dark:border-neutral-800 px-2 py-0.5 text-xs text-neutral-400 dark:text-neutral-600"
                title={t.description}
              >
                {t.label}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
