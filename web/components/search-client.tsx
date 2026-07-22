"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PlacementBadge, TechChips, sourceLabel } from "@/components/badges";
import type { SearchHit, SearchResponse } from "@/lib/api";

const SOURCES = ["lablab", "devpost", "ethglobal"] as const;

function HitCard({ hit }: { hit: SearchHit }) {
  return (
    <li className="py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/project/${encodeURIComponent(hit.id)}`}
              className="font-medium hover:underline underline-offset-2"
            >
              {hit.title}
            </Link>
            <PlacementBadge placement={hit.placement} isWinner={hit.is_winner} />
          </div>
          <div className="text-sm text-neutral-500">
            <Link
              href={`/hackathon/${encodeURIComponent(hit.hackathon_slug)}`}
              className="hover:underline underline-offset-2"
            >
              {hit.hackathon_name}
            </Link>{" "}
            · {sourceLabel(hit.source)}
          </div>
          {hit.description_excerpt && (
            <p className="text-sm text-neutral-600 dark:text-neutral-300 line-clamp-2">
              {hit.description_excerpt}
            </p>
          )}
          {hit.tech_stack.length > 0 && <TechChips items={hit.tech_stack} />}
        </div>
      </div>
    </li>
  );
}

export function SearchClient() {
  const router = useRouter();
  const params = useSearchParams();

  const urlQ = params.get("q") ?? "";
  const urlSources = params.getAll("source");
  const urlWinners = params.get("winners_only") === "true";

  // État du formulaire, initialisé depuis l'URL (résultats partageables / navigables).
  const [input, setInput] = useState(urlQ);
  const [sources, setSources] = useState<string[]>(urlSources);
  const [winnersOnly, setWinnersOnly] = useState(urlWinners);

  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  // Resynchronise les champs sur l'URL quand elle change hors saisie (back/forward, lien
  // partagé). `params` ne bouge qu'après un push (submit/toggle), jamais pendant la frappe,
  // donc ceci n'écrase pas ce que l'utilisateur est en train de taper.
  useEffect(() => {
    setInput(params.get("q") ?? "");
    setSources(params.getAll("source"));
    setWinnersOnly(params.get("winners_only") === "true");
  }, [params]);

  // Récrit l'URL à partir de l'état du formulaire ; le fetch est déclenché par le
  // changement d'URL (effet ci-dessous), pas directement, pour rester navigable.
  const pushSearch = useCallback(
    (q: string, srcs: string[], winners: boolean) => {
      const next = new URLSearchParams();
      if (q.trim()) next.set("q", q.trim());
      for (const s of srcs) next.append("source", s);
      if (winners) next.set("winners_only", "true");
      router.push(`/search?${next.toString()}`);
    },
    [router],
  );

  useEffect(() => {
    const q = params.get("q")?.trim();
    if (!q) {
      setData(null);
      setError(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    // Réutilise la query string de l'URL courante pour interroger le proxy /api/search.
    fetch(`/api/search?${params.toString()}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json() as Promise<SearchResponse>;
      })
      .then((json) => {
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        // Une requête abandonnée (URL changée entre-temps) ne doit ni afficher d'erreur
        // ni éteindre le spinner : la requête la plus récente reste en cours.
        if (err.name === "AbortError") return;
        setError(true);
        setLoading(false);
      });
    return () => controller.abort();
  }, [params]);

  function toggleSource(s: string) {
    const next = sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s];
    setSources(next);
    pushSearch(input, next, winnersOnly);
  }

  function toggleWinners() {
    const next = !winnersOnly;
    setWinnersOnly(next);
    pushSearch(input, sources, next);
  }

  const hasQuery = Boolean(params.get("q")?.trim());

  return (
    <div className="space-y-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          pushSearch(input, sources, winnersOnly);
        }}
        className="space-y-4"
      >
        <div className="flex gap-2">
          <input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Rechercher un projet, une idée, une techno…"
            aria-label="Rechercher un projet"
            autoFocus
            className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-transparent px-4 py-2.5 outline-none focus:border-neutral-500"
          />
          <button
            type="submit"
            className="rounded-lg bg-neutral-900 dark:bg-neutral-100 px-5 py-2.5 text-sm font-medium text-neutral-100 dark:text-neutral-900 hover:opacity-90"
          >
            Rechercher
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <span className="text-neutral-500">Sources :</span>
          {SOURCES.map((s) => (
            <label key={s} className="inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={sources.includes(s)}
                onChange={() => toggleSource(s)}
                className="accent-neutral-800 dark:accent-neutral-200"
              />
              {sourceLabel(s)}
            </label>
          ))}
          <label className="inline-flex items-center gap-1.5 cursor-pointer ml-auto">
            <input
              type="checkbox"
              checked={winnersOnly}
              onChange={toggleWinners}
              className="accent-amber-500"
            />
            Projets primés seulement
          </label>
        </div>
      </form>

      {loading && <div className="text-sm text-neutral-500">Recherche…</div>}

      {error && (
        <div className="text-sm text-red-600 dark:text-red-400">
          La recherche est momentanément indisponible. Réessaie dans un instant.
        </div>
      )}

      {!loading && !error && hasQuery && data && data.hits.length === 0 && (
        <div className="text-sm text-neutral-500">
          Aucun résultat pour « {data.query} ».
        </div>
      )}

      {!loading && !error && data && data.hits.length > 0 && (
        <>
          <div className="text-sm text-neutral-500">
            {data.total} résultat{data.total > 1 ? "s" : ""}
          </div>
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {data.hits.map((hit) => (
              <HitCard key={hit.id} hit={hit} />
            ))}
          </ul>
        </>
      )}

      {!hasQuery && !loading && (
        <p className="text-sm text-neutral-500">
          Recherche hybride : combine similarité sémantique (embeddings) et correspondance
          de mots-clés. Tape une idée de projet, un problème, ou une technologie.
        </p>
      )}
    </div>
  );
}
