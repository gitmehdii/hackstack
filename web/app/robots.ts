import type { MetadataRoute } from "next";

// Sitemap complet (par projet / hackathon) reporté : il nécessite un endpoint de
// listing, ajouté à l'Étape 3 avec la recherche. Ici on autorise simplement le crawl.
export default function robots(): MetadataRoute.Robots {
  const site = process.env.SITE_URL ?? "http://localhost:3000";
  return {
    rules: { userAgent: "*", allow: "/" },
    host: site,
  };
}
