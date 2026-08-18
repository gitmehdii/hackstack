// Client de l'API hackstack, utilisé uniquement côté serveur (Server Components).
// Le front ne touche jamais la base directement : il consomme l'API (cf. PROJECT.md).

const REVALIDATE_SECONDS = 86400; // ISR : 24 h

function apiBaseUrl(): string {
  const url = process.env.API_URL;
  if (!url) {
    throw new Error("API_URL non défini (voir web/.env.example)");
  }
  return url.replace(/\/$/, "");
}

export type ProjectSummary = {
  id: string;
  source: string;
  source_url: string;
  title: string;
  placement: number | null;
  raw_placement: string | null;
  is_winner: boolean;
  prize_track: string | null;
  team_name: string | null;
  tech_stack: string[];
  repo_url: string | null;
  demo_url: string | null;
};

export type ProjectDetail = {
  id: string;
  source: string;
  source_url: string;
  hackathon_slug: string;
  hackathon_name: string;
  hackathon_date: string | null;
  theme_tags: string[];
  title: string;
  description_excerpt: string | null;
  is_excerpt_truncated: boolean;
  placement: number | null;
  raw_placement: string | null;
  is_winner: boolean;
  prize_track: string | null;
  tech_stack: string[];
  stack_source: string;
  team_size: number | null;
  team_name: string | null;
  repo_url: string | null;
  demo_url: string | null;
  scraped_at: string;
};

export type HackathonAlternative = {
  source: string;
  slug: string;
  name: string;
  project_count: number;
};

export type HackathonDetail = {
  source: string;
  slug: string;
  name: string;
  hackathon_date: string | null;
  url: string | null;
  project_count: number;
  projects: ProjectSummary[];
  alternatives: HackathonAlternative[];
};

export type Stats = {
  projects: number;
  winners: number;
  hackathons: number;
  sources: number;
};

export type SearchHit = {
  id: string;
  source: string;
  source_url: string;
  title: string;
  description_excerpt: string | null;
  hackathon_slug: string;
  hackathon_name: string;
  is_winner: boolean;
  placement: number | null;
  tech_stack: string[];
  theme_tags: string[];
  score: number;
};

export type SearchResponse = {
  query: string;
  total: number;
  hits: SearchHit[];
};

export type StackCount = {
  name: string;
  count: number;
};

export type ThemeSummary = {
  slug: string;
  label: string;
  description: string;
  project_count: number;
  winner_count: number;
};

export type ThemeListResponse = {
  themes: ThemeSummary[];
};

export type ThemeDetail = {
  slug: string;
  label: string;
  description: string;
  project_count: number;
  winner_count: number;
  win_rate: number | null;
  top_stacks: StackCount[];
  projects: ProjectSummary[];
  methodology_note: string;
};

// --- Trends (Étape 5) ------------------------------------------------------------------

// Statut d'une analyse. "awaiting_date_backfill" et "unavailable_in_corpus" sont affichés
// différemment : le premier est une attente (Étape 6), le second une donnée peut-être jamais
// disponible.
export type AnalysisStatus =
  | "available"
  | "awaiting_date_backfill"
  | "unavailable_in_corpus";

export type SaturationPoint = {
  quarter: string;
  count: number;
  winner_count: number;
};

export type SaturationSeries = {
  status: AnalysisStatus;
  note: string;
  theme: string | null;
  points: SaturationPoint[];
};

export type LifecycleReport = {
  status: AnalysisStatus;
  note: string;
  theme: string | null;
  first_quarter: string | null;
  peak_quarter: string | null;
  last_quarter: string | null;
};

export type StackLift = {
  name: string;
  count: number;
  winner_count: number;
  loser_count: number;
  winner_share: number;
  baseline_share: number;
  lift: number;
  p_value: number | null;
  significant: boolean | null;
};

export type WinningStacks = {
  status: AnalysisStatus;
  note: string;
  caveat: string;
  theme: string | null;
  winners_total: number;
  losers_total: number;
  projects_total: number;
  techs: StackLift[];
};

export type TeamSizeCorrelation = {
  status: AnalysisStatus;
  note: string;
};

export type ThemeWinRate = {
  slug: string;
  label: string;
  project_count: number;
  winner_count: number;
  win_rate: number | null;
};

export type ThemeWinRates = {
  status: AnalysisStatus;
  methodology_note: string;
  themes: ThemeWinRate[];
};

export type TrendsOverview = {
  saturation: SaturationSeries;
  lifecycle: LifecycleReport;
  winning_stacks: WinningStacks;
  team_size: TeamSizeCorrelation;
  theme_win_rates: ThemeWinRates;
};

export type SimilarProject = {
  id: string;
  source: string;
  source_url: string;
  title: string;
  hackathon_slug: string;
  hackathon_name: string;
  is_winner: boolean;
  placement: number | null;
  tech_stack: string[];
  distance: number;
};

// `tolerateOutage` fait retomber une API *indisponible* (5xx, ou injoignable) sur `null`
// au lieu de lever. Réservé aux pages d'index, qui savent toutes afficher un état vide.
//
// La raison est un incident réel : la base s'est arrêtée, `/stats` a renvoyé 500, et le
// prérendu de `/` a fait échouer le build entier. Le front est resté non déployable pendant
// trois semaines, pendant que Vercel continuait de servir le dernier build réussi — donc
// le site avait l'air vivant. Un front doit pouvoir se déployer même API éteinte.
//
// Volontairement NON appliqué aux pages de détail : là, `null` veut dire « ce projet
// n'existe pas » et déclenche un notFound() mis en cache. Confondre une panne avec une
// absence transformerait une base endormie en 404 durables sur des pages valides.
// Un 4xx autre que 404 lève dans tous les cas : c'est un bug d'appel, pas une panne.
type FetchOptions = { tolerateOutage?: boolean };

async function fetchJson<T>(
  path: string,
  { tolerateOutage = false }: FetchOptions = {},
): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl()}${path}`, {
      next: { revalidate: REVALIDATE_SECONDS },
      headers: { accept: "application/json" },
    });
  } catch (err) {
    if (tolerateOutage) {
      console.error(`API injoignable sur ${path}, rendu en état vide`, err);
      return null;
    }
    throw err;
  }
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    if (tolerateOutage && res.status >= 500) {
      console.error(`API ${path} → ${res.status}, rendu en état vide`);
      return null;
    }
    throw new Error(`API ${path} → ${res.status}`);
  }
  return (await res.json()) as T;
}

export function getProject(id: string): Promise<ProjectDetail | null> {
  return fetchJson<ProjectDetail>(`/projects/${encodeURIComponent(id)}`);
}

export function getHackathon(slug: string): Promise<HackathonDetail | null> {
  return fetchJson<HackathonDetail>(`/hackathons/${encodeURIComponent(slug)}`);
}

export async function getStats(): Promise<Stats | null> {
  return fetchJson<Stats>(`/stats`, { tolerateOutage: true });
}

export async function getThemes(): Promise<ThemeListResponse | null> {
  return fetchJson<ThemeListResponse>(`/themes`, { tolerateOutage: true });
}

export function getTheme(slug: string): Promise<ThemeDetail | null> {
  return fetchJson<ThemeDetail>(`/themes/${encodeURIComponent(slug)}`);
}

export function getTrends(): Promise<TrendsOverview | null> {
  return fetchJson<TrendsOverview>(`/trends`, { tolerateOutage: true });
}

// Projets similaires : rendu côté serveur sur la page projet (donc mis en cache ISR
// avec elle). Renvoie [] si l'API échoue ou si le projet n'a pas encore d'embedding.
export async function getSimilar(id: string, limit = 6): Promise<SimilarProject[]> {
  const res = await fetch(
    `${apiBaseUrl()}/projects/${encodeURIComponent(id)}/similar?limit=${limit}`,
    { next: { revalidate: REVALIDATE_SECONDS }, headers: { accept: "application/json" } },
  );
  if (!res.ok) {
    return [];
  }
  return (await res.json()) as SimilarProject[];
}

// Recherche : appelée côté serveur par le Route Handler /api/search, qui relaie la
// query string du client vers l'API. `qs` est déjà encodé (URLSearchParams). Pas de
// cache : les résultats de recherche sont dynamiques.
export async function searchProjects(qs: string): Promise<SearchResponse> {
  const res = await fetch(`${apiBaseUrl()}/search?${qs}`, {
    cache: "no-store",
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`API /search → ${res.status}`);
  }
  return (await res.json()) as SearchResponse;
}
