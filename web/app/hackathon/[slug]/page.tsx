import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  PlacementBadge,
  SourceBadge,
  TechChips,
  sourceLabel,
} from "@/components/badges";
import { getHackathon, type ProjectSummary } from "@/lib/api";

export const revalidate = 86400;
export const dynamicParams = true;

// Pages générées à la demande puis mises en cache (ISR).
export function generateStaticParams(): { slug: string }[] {
  return [];
}

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const hackathon = await getHackathon(slug);
  if (!hackathon) {
    return { title: "Hackathon introuvable" };
  }
  const description = `${hackathon.project_count} projets référencés pour ${hackathon.name} (${sourceLabel(
    hackathon.source,
  )}).`;
  return {
    title: hackathon.name,
    description,
    openGraph: { title: hackathon.name, description, type: "website" },
  };
}

function ProjectRow({ project }: { project: ProjectSummary }) {
  return (
    <li className="py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1.5">
          <Link
            href={`/project/${encodeURIComponent(project.id)}`}
            className="font-medium hover:underline underline-offset-2"
          >
            {project.title}
          </Link>
          {project.team_name && (
            <div className="text-sm text-neutral-500">équipe {project.team_name}</div>
          )}
          {project.tech_stack.length > 0 && <TechChips items={project.tech_stack} />}
        </div>
        <div className="shrink-0">
          <PlacementBadge placement={project.placement} isWinner={project.is_winner} />
        </div>
      </div>
    </li>
  );
}

export default async function HackathonPage({ params }: Params) {
  const { slug } = await params;
  const hackathon = await getHackathon(slug);
  if (!hackathon) {
    notFound();
  }

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <SourceBadge source={hackathon.source} />
        <h1 className="text-3xl font-bold tracking-tight">{hackathon.name}</h1>
        <p className="text-neutral-500">
          {hackathon.project_count} projet{hackathon.project_count > 1 ? "s" : ""} référencé
          {hackathon.project_count > 1 ? "s" : ""}
          {hackathon.hackathon_date && <> · {hackathon.hackathon_date}</>}
        </p>
        {hackathon.url && (
          <a
            href={hackathon.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block text-sm underline underline-offset-2 text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
          >
            Page de l&apos;événement ↗
          </a>
        )}
      </header>

      {hackathon.alternatives.length > 0 && (
        <p className="rounded-md border border-neutral-200 dark:border-neutral-800 bg-neutral-100/50 dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-500">
          Un hackathon du même slug existe aussi sur{" "}
          {hackathon.alternatives.map((a) => sourceLabel(a.source)).join(", ")}. Cette page
          montre la source la plus fournie ({sourceLabel(hackathon.source)}).
        </p>
      )}

      <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
        {hackathon.projects.map((p) => (
          <ProjectRow key={p.id} project={p} />
        ))}
      </ul>
    </div>
  );
}
