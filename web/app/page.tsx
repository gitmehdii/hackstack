import Link from "next/link";

import { getStats, getThemes } from "@/lib/api";

export const revalidate = 86400;

// Nombre de thèmes proposés en entrée de parcours. Assez pour montrer la variété du
// corpus, pas assez pour transformer la home en index — `/themes` est là pour ça.
const HOME_THEMES = 12;

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-5">
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-neutral-500">{label}</div>
    </div>
  );
}

export default async function HomePage() {
  // Les deux appels sont indépendants : les paralléliser évite d'ajouter un aller-retour
  // séquentiel au rendu de la page la plus visitée.
  const [stats, themes] = await Promise.all([getStats(), getThemes()]);
  const fmt = new Intl.NumberFormat("fr-FR");
  const topThemes = (themes?.themes ?? [])
    .slice()
    .sort((a, b) => b.project_count - a.project_count)
    .slice(0, HOME_THEMES);

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">
          Ce qui gagne les hackathons.
        </h1>
        <p className="max-w-2xl text-neutral-600 dark:text-neutral-300">
          Une base de données des projets primés sur lablab.ai, Devpost et ETHGlobal.
          Cherche par idée, problème ou technologie — la recherche combine sémantique et
          mots-clés.
        </p>
        <form action="/search" method="get" className="flex max-w-2xl gap-2">
          <input
            type="search"
            name="q"
            placeholder="Rechercher un projet, une idée, une techno…"
            aria-label="Rechercher un projet"
            className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-transparent px-4 py-2.5 outline-none focus:border-neutral-500"
          />
          <button
            type="submit"
            className="rounded-lg bg-neutral-900 dark:bg-neutral-100 px-5 py-2.5 text-sm font-medium text-neutral-100 dark:text-neutral-900 hover:opacity-90"
          >
            Rechercher
          </button>
        </form>
      </section>

      {stats && (
        <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat value={fmt.format(stats.projects)} label="projets" />
          <Stat value={fmt.format(stats.winners)} label="projets primés" />
          <Stat value={fmt.format(stats.hackathons)} label="hackathons" />
          <Stat value={fmt.format(stats.sources)} label="sources" />
        </section>
      )}

      {topThemes.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold">Explorer par thème</h2>
            <Link href="/themes" className="text-sm text-neutral-500 hover:underline">
              Tous les thèmes →
            </Link>
          </div>
          <ul className="flex flex-wrap gap-2">
            {topThemes.map((theme) => (
              <li key={theme.slug}>
                <Link
                  href={`/theme/${theme.slug}`}
                  className="inline-flex items-baseline gap-2 rounded-full border border-neutral-300 dark:border-neutral-700 px-3 py-1.5 text-sm hover:border-neutral-500"
                >
                  {theme.label}
                  <span className="text-xs tabular-nums text-neutral-500">
                    {fmt.format(theme.project_count)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="text-sm text-neutral-500">
        Voir aussi les{" "}
        <Link href="/trends" className="underline hover:no-underline">
          tendances
        </Link>{" "}
        : volume par thème, stacks sur-représentées chez les gagnants, avec les réserves
        méthodologiques qui s&apos;imposent.
      </section>
    </div>
  );
}
