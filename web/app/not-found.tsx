import Link from "next/link";

export default function NotFound() {
  return (
    <div className="space-y-4 py-12 text-center">
      <h1 className="text-2xl font-semibold">Introuvable</h1>
      <p className="text-neutral-500">Cette page n&apos;existe pas ou plus.</p>
      <Link href="/" className="inline-block underline underline-offset-2">
        Retour à l&apos;accueil
      </Link>
    </div>
  );
}
