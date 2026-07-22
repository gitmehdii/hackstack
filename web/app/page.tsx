import { getStats } from "@/lib/api";

export const revalidate = 86400;

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-5">
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-neutral-500">{label}</div>
    </div>
  );
}

export default async function HomePage() {
  const stats = await getStats();
  const fmt = new Intl.NumberFormat("fr-FR");

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

      <section className="text-sm text-neutral-500">
        Les pages de tendances (volume par thème, stacks gagnantes) arrivent aux étapes
        suivantes.
      </section>
    </div>
  );
}
