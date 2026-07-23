import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

const siteName = "hackstack";
const siteDescription =
  "Base de données publique des projets de hackathon gagnants : recherche et tendances.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3000"),
  title: {
    default: `${siteName} — projets de hackathon gagnants`,
    template: `%s · ${siteName}`,
  },
  description: siteDescription,
  openGraph: {
    siteName,
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto max-w-5xl px-4 py-4 flex items-center justify-between">
            <Link href="/" className="font-semibold tracking-tight text-lg">
              hackstack
            </Link>
            <nav className="flex items-center gap-4">
              <Link
                href="/themes"
                className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
              >
                Thèmes
              </Link>
              <Link
                href="/trends"
                className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
              >
                Tendances
              </Link>
              <Link
                href="/search"
                className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
              >
                Recherche
              </Link>
            </nav>
          </div>
        </header>
        <main className="flex-1">
          <div className="mx-auto max-w-5xl px-4 py-8">{children}</div>
        </main>
        <footer className="border-t border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto max-w-5xl px-4 py-6 text-sm text-neutral-500">
            Données agrégées depuis lablab.ai, Devpost et ETHGlobal. Extraits seulement —
            chaque projet renvoie vers sa source d&apos;origine.
          </div>
        </footer>
      </body>
    </html>
  );
}
