import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PlacementBadge, SourceBadge, TechChips, sourceLabel } from "@/components/badges";
import { getProject } from "@/lib/api";

// ISR : pages générées à la demande puis mises en cache 24 h.
export const revalidate = 86400;
export const dynamicParams = true;

// Aucune page pré-rendue au build (21k projets) : tout est généré à la première
// visite puis mis en cache (ISR). generateStaticParams vide force ce mode statique.
export function generateStaticParams(): { id: string }[] {
  return [];
}

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const project = await getProject(id);
  if (!project) {
    return { title: "Projet introuvable" };
  }
  const description =
    project.description_excerpt ??
    `Projet présenté à ${project.hackathon_name} (${sourceLabel(project.source)}).`;
  return {
    title: project.title,
    description,
    openGraph: {
      title: project.title,
      description,
      type: "article",
    },
  };
}

function ExternalLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded-md border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800"
    >
      {label} ↗
    </a>
  );
}

export default async function ProjectPage({ params }: Params) {
  const { id } = await params;
  const project = await getProject(id);
  if (!project) {
    notFound();
  }

  return (
    <article className="space-y-8">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <SourceBadge source={project.source} />
          <PlacementBadge placement={project.placement} isWinner={project.is_winner} />
          {project.prize_track && (
            <span className="text-xs text-neutral-500">{project.prize_track}</span>
          )}
        </div>
        <h1 className="text-3xl font-bold tracking-tight">{project.title}</h1>
        <p className="text-neutral-600 dark:text-neutral-300">
          Présenté à{" "}
          <Link
            href={`/hackathon/${encodeURIComponent(project.hackathon_slug)}`}
            className="underline underline-offset-2 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            {project.hackathon_name}
          </Link>
          {project.team_name && <> · équipe {project.team_name}</>}
        </p>
      </header>

      {project.description_excerpt && (
        <section className="space-y-2">
          <p className="whitespace-pre-line leading-relaxed text-neutral-800 dark:text-neutral-200">
            {project.description_excerpt}
          </p>
          {project.is_excerpt_truncated && (
            <p className="text-sm text-neutral-500">
              Extrait — lire la description complète sur la source d&apos;origine.
            </p>
          )}
        </section>
      )}

      {project.tech_stack.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-neutral-500">Stack</h2>
          <TechChips items={project.tech_stack} />
        </section>
      )}

      <section className="flex flex-wrap gap-2">
        <ExternalLink href={project.source_url} label={`Voir sur ${sourceLabel(project.source)}`} />
        {project.repo_url && <ExternalLink href={project.repo_url} label="Code" />}
        {project.demo_url && <ExternalLink href={project.demo_url} label="Démo" />}
      </section>
    </article>
  );
}
