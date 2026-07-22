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
      <section className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">
          Ce qui gagne les hackathons.
        </h1>
        <p className="max-w-2xl text-neutral-600 dark:text-neutral-300">
          Une base de données des projets primés sur lablab.ai, Devpost et ETHGlobal.
          Explore les palmarès, les stacks et — bientôt — la recherche sémantique et les
          tendances.
        </p>
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
        La recherche et les pages de tendances arrivent aux étapes suivantes. Pour
        l&apos;instant, accède à un projet via son identifiant ou à un hackathon via son
        slug.
      </section>
    </div>
  );
}
