import { Suspense } from "react";
import type { Metadata } from "next";

import { SearchClient } from "@/components/search-client";

export const metadata: Metadata = {
  title: "Recherche",
  description:
    "Recherche hybride (sémantique + mots-clés) dans les projets de hackathon primés.",
};

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="text-sm text-neutral-500">Chargement…</div>}>
      <SearchClient />
    </Suspense>
  );
}
