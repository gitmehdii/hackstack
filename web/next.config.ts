import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Le front ne fait que consommer l'API : pas d'accès direct à la base.
  // L'URL de l'API est fournie par API_URL (serveur) au moment du fetch.
  reactStrictMode: true,
};

export default nextConfig;
