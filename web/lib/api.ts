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

async function fetchJson<T>(path: string): Promise<T | null> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    next: { revalidate: REVALIDATE_SECONDS },
    headers: { accept: "application/json" },
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
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
  return fetchJson<Stats>(`/stats`);
}
