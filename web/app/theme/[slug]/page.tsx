import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PlacementBadge, SourceBadge, TechChips } from "@/components/badges";
import { getTheme, type ProjectSummary } from "@/lib/api";

export const revalidate = 86400;
export const dynamicParams = true;

// Pages générées à la demande puis mises en cache (ISR), comme projet/hackathon.
export function generateStaticParams(): { slug: string }[] {
  return [];
}

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const theme = await getTheme(slug);
  if (!theme) {
    return { title: "Thème introuvable" };
  }
  const description = `${theme.project_count} projets sur le thème « ${theme.label} » — ${theme.description}`;
  return {
    title: theme.label,
    description,
    openGraph: { title: theme.label, description, type: "website" },
  };
}

function ProjectRow({ project }: { project: ProjectSummary }) {
  return (
    <li className="py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            <Link
              href={`/project/${encodeURIComponent(project.id)}`}
              className="font-medium hover:underline underline-offset-2"
            >
              {project.title}
            </Link>
            <SourceBadge source={project.source} />
          </div>
          {project.tech_stack.length > 0 && <TechChips items={project.tech_stack.slice(0, 6)} />}
        </div>
        <div className="shrink-0">
          <PlacementBadge placement={project.placement} isWinner={project.is_winner} />
        </div>
      </div>
    </li>
  );
}

export default async function ThemePage({ params }: Params) {
  const { slug } = await params;
  const theme = await getTheme(slug);
  if (!theme) {
    notFound();
  }

  const winPct =
    theme.win_rate === null ? null : `${Math.round(theme.win_rate * 100)} %`;

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <Link
          href="/themes"
          className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        >
          ← Tous les thèmes
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">{theme.label}</h1>
        <p className="text-neutral-500">{theme.description}</p>
      </header>

      {theme.project_count === 0 ? (
        <p className="rounded-md border border-neutral-200 dark:border-neutral-800 bg-neutral-100/50 dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-500">
          Aucun projet encore associé à ce thème. L&apos;extraction sur l&apos;ensemble du
          corpus est en cours.
        </p>
      ) : (
        <>
          <section className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <Stat label="Projets" value={theme.project_count.toLocaleString("fr")} />
            <Stat label="Gagnants" value={theme.winner_count.toLocaleString("fr")} />
            <Stat label="Taux de victoire*" value={winPct ?? "—"} />
          </section>

          {/* Contrainte PROJECT.md : ne jamais présenter le taux de victoire sans le biais. */}
          <p className="text-xs leading-relaxed text-neutral-500 border-l-2 border-neutral-300 dark:border-neutral-700 pl-3">
            * {theme.methodology_note}
          </p>

          {theme.top_stacks.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-medium text-neutral-500">Stacks dominantes</h2>
              <div className="flex flex-wrap gap-2">
                {theme.top_stacks.map((s) => (
                  <span
                    key={s.name}
                    className="inline-flex items-center gap-1.5 rounded bg-neutral-200/70 dark:bg-neutral-800 px-2 py-1 text-xs text-neutral-700 dark:text-neutral-300"
                  >
                    {s.name}
                    <span className="text-neutral-500 dark:text-neutral-500">{s.count}</span>
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-neutral-500">
              Projets{theme.projects.length < theme.project_count && " (extrait)"}
            </h2>
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {theme.projects.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 px-4 py-3">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-neutral-500 mt-0.5">{label}</div>
    </div>
  );
}
