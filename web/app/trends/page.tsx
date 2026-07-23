import type { Metadata } from "next";
import Link from "next/link";

import {
  getTrends,
  type AnalysisStatus,
  type StackLift,
  type ThemeWinRate,
  type WinningStacks,
} from "@/lib/api";

export const revalidate = 86400;

export const metadata: Metadata = {
  title: "Tendances",
  description:
    "Analyses de tendances des projets de hackathon : stacks des gagnants, taux de victoire par thème, saturation. Avec note méthodologique sur les biais.",
};

// Pastille de statut d'une analyse. Trois états distincts, affichés différemment :
// disponible / en attente du backfill des dates (Étape 6) / donnée absente du corpus.
function StatusPill({ status }: { status: AnalysisStatus }) {
  const map: Record<AnalysisStatus, { label: string; cls: string }> = {
    available: {
      label: "Disponible",
      cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
    },
    awaiting_date_backfill: {
      label: "En attente — backfill Étape 6",
      cls: "bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-300",
    },
    unavailable_in_corpus: {
      label: "Donnée absente du corpus",
      cls: "bg-neutral-200 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400",
    },
  };
  const { label, cls } = map[status];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function AnalysisCard({
  n,
  title,
  subtitle,
  status,
  children,
}: {
  n: number;
  title: string;
  subtitle: string;
  status: AnalysisStatus;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-5 space-y-4">
      <header className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">
            <span className="text-neutral-400 dark:text-neutral-600 tabular-nums mr-2">
              {n}.
            </span>
            {title}
          </h2>
          <StatusPill status={status} />
        </div>
        <p className="text-sm text-neutral-500">{subtitle}</p>
      </header>
      {children}
    </section>
  );
}

// État vide expliqué. Le ton diffère selon le statut : une attente (la donnée arrive) vs
// une absence structurelle (rien ne la garantit).
function EmptyState({ status, note }: { status: AnalysisStatus; note: string }) {
  const awaiting = status === "awaiting_date_backfill";
  const border = awaiting
    ? "border-amber-300 dark:border-amber-500/30"
    : "border-neutral-300 dark:border-neutral-700";
  return (
    <div
      className={`rounded-md border border-dashed ${border} bg-neutral-50/50 dark:bg-neutral-900/50 px-4 py-4 text-sm text-neutral-600 dark:text-neutral-400`}
    >
      <p className="font-medium text-neutral-700 dark:text-neutral-300 mb-1">
        {awaiting ? "Analyse en attente de données" : "Analyse indisponible"}
      </p>
      {note}
    </div>
  );
}

// Barre horizontale (SVG-free : div à largeur proportionnelle). `pct` dans [0, 1].
function Bar({ pct, className }: { pct: number; className: string }) {
  return (
    <div className="h-2 rounded-full bg-neutral-200/70 dark:bg-neutral-800 overflow-hidden">
      <div
        className={`h-full rounded-full ${className}`}
        style={{ width: `${Math.max(2, Math.round(pct * 100))}%` }}
      />
    </div>
  );
}

function fmt(n: number): string {
  return n.toLocaleString("fr");
}

function pct(x: number | null): string {
  return x === null ? "—" : `${(x * 100).toFixed(1)} %`;
}

// Analyse 3 — stacks des gagnants. Le lift ≈ 1 sur le corpus actuel ; on montre donc la
// fréquence (nombre) et on annote le lift + la significativité, sous un caveat fort.
function WinningStacksView({ data }: { data: WinningStacks }) {
  const maxCount = Math.max(1, ...data.techs.map((t) => t.count));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3 text-center">
        <MiniStat label="Projets (avec stack)" value={fmt(data.projects_total)} />
        <MiniStat label="dont gagnants" value={fmt(data.winners_total)} />
        <MiniStat label="dont non-gagnants" value={fmt(data.losers_total)} />
      </div>

      {/* Caveat non négociable (PROJECT.md : pas de chiffre biaisé présenté comme conclusion). */}
      <p className="text-xs leading-relaxed text-neutral-500 border-l-2 border-amber-400 dark:border-amber-500/40 pl-3">
        {data.caveat}
      </p>

      <ul className="space-y-2.5">
        {data.techs.map((t: StackLift) => (
          <li key={t.name} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium">{t.name}</span>
              <span className="tabular-nums text-neutral-500">
                {fmt(t.count)} · lift {t.lift.toFixed(2)}
                {t.significant === true && (
                  <span
                    className="ml-1 text-amber-600 dark:text-amber-400"
                    title="Différence « significative » — mais confondue par la source (cf. note ci-dessus)"
                  >
                    ✻
                  </span>
                )}
              </span>
            </div>
            <Bar pct={t.count / maxCount} className="bg-neutral-400 dark:bg-neutral-500" />
          </li>
        ))}
      </ul>
      <p className="text-xs text-neutral-400 dark:text-neutral-600">
        ✻ écart « significatif » au test z — à lire avec la réserve de source ci-dessus, ce
        n&apos;est pas un effet de victoire.
      </p>
    </div>
  );
}

// Analyse 5 — thèmes fort volume / faible taux de victoire. Volume en barre, taux annoté.
function ThemeWinRatesView({ themes, note }: { themes: ThemeWinRate[]; note: string }) {
  const top = themes.slice(0, 12);
  const maxVol = Math.max(1, ...top.map((t) => t.project_count));
  // Fort volume (≥ 500) trié par taux de victoire croissant : le cœur de l'analyse 5.
  const lowWin = themes
    .filter((t) => t.project_count >= 500 && t.win_rate !== null)
    .sort((a, b) => (a.win_rate ?? 0) - (b.win_rate ?? 0))
    .slice(0, 5);

  return (
    <div className="space-y-5">
      <ul className="space-y-2.5">
        {top.map((t) => (
          <li key={t.slug} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <Link
                href={`/theme/${encodeURIComponent(t.slug)}`}
                className="font-medium hover:underline underline-offset-2"
              >
                {t.label}
              </Link>
              <span className="tabular-nums text-neutral-500">
                {fmt(t.project_count)} · {pct(t.win_rate)}
              </span>
            </div>
            <Bar pct={t.project_count / maxVol} className="bg-neutral-400 dark:bg-neutral-500" />
          </li>
        ))}
      </ul>

      {lowWin.length > 0 && (
        <div className="rounded-md bg-neutral-100/60 dark:bg-neutral-900 px-4 py-3 space-y-2">
          <h3 className="text-sm font-medium">
            Fort volume, taux de victoire le plus bas (≥ 500 projets)
          </h3>
          <ul className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
            {lowWin.map((t) => (
              <li key={t.slug} className="flex justify-between gap-3">
                <Link
                  href={`/theme/${encodeURIComponent(t.slug)}`}
                  className="hover:underline underline-offset-2"
                >
                  {t.label}
                </Link>
                <span className="tabular-nums">
                  {pct(t.win_rate)} · {fmt(t.project_count)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs leading-relaxed text-neutral-500 border-l-2 border-neutral-300 dark:border-neutral-700 pl-3">
        {note}
      </p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-neutral-200 dark:border-neutral-800 px-2 py-2">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] leading-tight text-neutral-500 mt-0.5">{label}</div>
    </div>
  );
}

export default async function TrendsPage() {
  const trends = await getTrends();

  if (!trends) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Tendances</h1>
        <p className="text-neutral-500">Tendances momentanément indisponibles.</p>
      </div>
    );
  }

  const { saturation, lifecycle, winning_stacks, team_size, theme_win_rates } = trends;

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">Tendances</h1>
        <p className="text-neutral-500">
          Cinq analyses sur l&apos;ensemble du corpus. Chacune indique son statut : les
          analyses temporelles s&apos;activeront quand les dates d&apos;événement seront
          renseignées (Étape 6).
        </p>
      </header>

      {/* Note méthodologique globale, lue avant les chiffres. */}
      <div className="rounded-lg border-l-4 border-amber-400 dark:border-amber-500/50 bg-amber-50/60 dark:bg-amber-500/5 px-4 py-3 text-sm text-neutral-700 dark:text-neutral-300 space-y-1">
        <p className="font-medium">Note méthodologique</p>
        <p className="text-neutral-600 dark:text-neutral-400">
          Le corpus est composé à ~99 % de projets gagnants (les non-gagnants ne viennent que
          de lablab.ai). Les taux de victoire et les comparaisons gagnants/ensemble sont donc
          biaisés et fournis comme indicateurs, jamais comme conclusions. La normalisation par
          nombre de prix, idéale, n&apos;est pas possible : cette information n&apos;est pas
          dans le corpus.
        </p>
      </div>

      <div className="space-y-5">
        <AnalysisCard
          n={1}
          title="Saturation d'un thème"
          subtitle="Fréquence par trimestre, superposée au taux de victoire."
          status={saturation.status}
        >
          <EmptyState status={saturation.status} note={saturation.note} />
        </AnalysisCard>

        <AnalysisCard
          n={2}
          title="Durée de vie d'une tendance"
          subtitle="Premier projet, pic, déclin."
          status={lifecycle.status}
        >
          <EmptyState status={lifecycle.status} note={lifecycle.note} />
        </AnalysisCard>

        <AnalysisCard
          n={3}
          title="Stacks des gagnants vs l'ensemble"
          subtitle="Technologies sur-représentées chez les gagnants, avec test statistique."
          status={winning_stacks.status}
        >
          {winning_stacks.techs.length > 0 ? (
            <WinningStacksView data={winning_stacks} />
          ) : (
            <EmptyState status={winning_stacks.status} note={winning_stacks.note} />
          )}
        </AnalysisCard>

        <AnalysisCard
          n={4}
          title="Taille d'équipe et classement"
          subtitle="Corrélation entre la composition des équipes et le rang final."
          status={team_size.status}
        >
          <EmptyState status={team_size.status} note={team_size.note} />
        </AnalysisCard>

        <AnalysisCard
          n={5}
          title="Thèmes à fort volume et faible taux de victoire"
          subtitle="Volume par thème et part de gagnants."
          status={theme_win_rates.status}
        >
          {theme_win_rates.themes.length > 0 ? (
            <ThemeWinRatesView
              themes={theme_win_rates.themes}
              note={theme_win_rates.methodology_note}
            />
          ) : (
            <EmptyState status={theme_win_rates.status} note={theme_win_rates.methodology_note} />
          )}
        </AnalysisCard>
      </div>
    </div>
  );
}
