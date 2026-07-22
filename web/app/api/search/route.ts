import { NextRequest, NextResponse } from "next/server";

import { searchProjects } from "@/lib/api";

// Recherche dynamique : jamais mise en cache.
export const dynamic = "force-dynamic";

// Proxy serveur vers l'API : le client parle à cette route de même origine, l'URL de
// l'API (API_URL) reste privée. On relaie les paramètres autorisés vers le backend.
const ALLOWED = new Set(["q", "source", "winners_only", "since", "until", "limit"]);

export async function GET(request: NextRequest): Promise<NextResponse> {
  const incoming = request.nextUrl.searchParams;
  const q = incoming.get("q")?.trim();
  if (!q) {
    return NextResponse.json({ error: "Paramètre q requis" }, { status: 400 });
  }

  const out = new URLSearchParams();
  for (const [key, value] of incoming.entries()) {
    if (ALLOWED.has(key) && value !== "") {
      out.append(key, value);
    }
  }

  try {
    const data = await searchProjects(out.toString());
    return NextResponse.json(data);
  } catch (err) {
    console.error("search proxy error", err);
    return NextResponse.json({ error: "Recherche indisponible" }, { status: 502 });
  }
}
