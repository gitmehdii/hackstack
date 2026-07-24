"""Anonymise les descriptions intégrales dans les fixtures de contrat (Étape 7).

Les fixtures de `pipeline/contracts/fixtures/` sont des captures live figées : elles servent
à tester le *parsing* (sélecteurs, cadre RSC), pas le contenu. Or elles contenaient le texte
intégral de descriptions de projets — ce que PROJECT.md interdit de republier. Le repo ayant
vocation à devenir public, ce script remplace ces textes par du filler synthétique **de
longueur suffisante** pour que les invariants de parsing tiennent (les tests vérifient
`len(description) > 80/200`), en **préservant la structure** :

  - ethglobal : la valeur inline `"description"` (hors référence `$NN`) et le corps de tous
    les chunks texte RSC `NN:T<hex>,…` (qui portent les prose référencées) ; le préfixe de
    longueur `T<hex>` est recalculé pour rester cohérent, et les références `$NN` sont
    laissées intactes (le test de résolution de référence doit continuer d'exercer le chunk).
  - devpost : la prose de `#app-details-left` (en gardant `#built-with` et `.app-links`,
    nécessaires aux tests) + les `<meta … description>`.
  - lablab : le champ `description` de chaque submission (le `shortDescription`, un extrait
    court, est conservé — c'est ce que le site expose déjà publiquement).

Ré-exécutable et idempotent : à relancer si une fixture est re-capturée.

    python -m pipeline.contracts.scrub_fixtures            # scrub en place
    python -m pipeline.contracts.scrub_fixtures --check     # échoue si un résidu subsiste
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Filler ASCII pur : ni guillemet, ni antislash, ni `$`, ni `<`/`>` — sûr en JSON, en RSC et
# en HTML sans ré-échappement.
_SENTENCE = (
    "Placeholder description text substituted for the original project write up during "
    "fixture scrubbing to avoid republishing full user descriptions in a public repository. "
)
FILLER_SHORT = (_SENTENCE * 2)[:220]  # > 80 et > 200
FILLER_LONG = (_SENTENCE * 3)[:340]  # > 200
FILLER_META = "Placeholder meta description substituted during fixture scrubbing."
FILLER_DEVPOST = (
    '<div class="scrubbed-description"><p>' + (_SENTENCE * 3)[:420] + "</p></div>\n      "
)

# --------------------------------------------------------------------------- ethglobal

# Chunk texte RSC : self.__next_f.push([1,"NN:T<hex>,<corps>"])
_T_CHUNK_RE = re.compile(
    r'(self\.__next_f\.push\(\[1,")(\w+:T)([0-9a-fA-F]+)(,)((?:[^"\\]|\\.)*)("\]\))'
)
# Push RSC « nu » : payload SANS préfixe d'id `hex:` — une continuation de texte streamée à
# part (la prose y fuit hors des chunks `NN:T…`). Les payloads structurels commencent tous
# par `NN:` (id de chunk), donc le lookahead les épargne ; le parser ne lit que ces derniers.
_BARE_PUSH_RE = re.compile(
    r'(self\.__next_f\.push\(\[1,")(?![0-9a-fA-F]+:)((?:[^"\\]|\\.)+)("\]\))'
)
# Valeur inline d'un champ prose, hors référence RSC ($NN) : "key\":\"<valeur>\",\"
_INLINE_RE = re.compile(r'((?:description|howItsMade)\\":\\")(?!\$)((?:[^"\\]|\\.)*?)(\\",\\")')

# La page Next.js REND aussi la prose en DOM (indépendamment du payload RSC) : conteneur
# « Project Description » / « How it's Made ». On remplace son contenu (matching <div> en
# comptant la profondeur), pour ne pas laisser la copie rendue de la description.
_PROSE_DIV = '<div class="text-black-500 text-md lg:text-base">'
_PROSE_FILLER = f'<p class="mt-4 mb-2">{FILLER_LONG}</p>'
_DIV_TOKEN_RE = re.compile(r"</?div\b")


def _scrub_t_chunk(m: re.Match[str]) -> str:
    body = FILLER_LONG
    return f"{m.group(1)}{m.group(2)}{len(body):x}{m.group(4)}{body}{m.group(6)}"


def _replace_container_inner(html: str, opening: str, filler: str) -> str:
    """Remplace le contenu de chaque conteneur `opening` … `</div>` (profondeur comptée)."""
    out: list[str] = []
    idx = 0
    while True:
        pos = html.find(opening, idx)
        if pos == -1:
            out.append(html[idx:])
            return "".join(out)
        inner_start = pos + len(opening)
        depth = 1
        close_start = len(html)
        for m in _DIV_TOKEN_RE.finditer(html, inner_start):
            depth += -1 if m.group().startswith("</") else 1
            if depth == 0:
                close_start = m.start()
                break
        out.append(html[idx:inner_start])
        out.append(filler)
        idx = close_start  # on conserve le </div> fermant


def scrub_ethglobal(html: str) -> str:
    html = _INLINE_RE.sub(lambda m: f"{m.group(1)}{FILLER_SHORT}{m.group(3)}", html)
    html = _T_CHUNK_RE.sub(_scrub_t_chunk, html)
    html = _BARE_PUSH_RE.sub(lambda m: f"{m.group(1)}{FILLER_LONG}{m.group(3)}", html)
    html = _replace_container_inner(html, _PROSE_DIV, _PROSE_FILLER)
    return html


# --------------------------------------------------------------------------- devpost

_META_RE = re.compile(r"<meta\b[^>]*>")
_META_IDS = (
    'name="description"',
    'property="og:description"',
    'name="twitter:description"',
    'itemprop="description"',
)


def _scrub_meta(m: re.Match[str]) -> str:
    tag = m.group(0)
    if any(idf in tag for idf in _META_IDS):
        tag = re.sub(r'content="[^"]*"', f'content="{FILLER_META}"', tag)
    return tag


def scrub_devpost_software(html: str) -> str:
    adl = html.find('id="app-details-left"')
    bw = html.find('id="built-with"')
    if adl != -1 and bw != -1:
        open_end = html.find(">", adl)
        bw_tag = html.rfind("<", 0, bw)
        if open_end != -1 and bw_tag != -1 and open_end < bw_tag:
            html = html[: open_end + 1] + "\n      " + FILLER_DEVPOST + html[bw_tag:]
    return _META_RE.sub(_scrub_meta, html)


# --------------------------------------------------------------------------- lablab


def scrub_lablab_json(text: str) -> str:
    data = json.loads(text)
    for sub in data.get("submissions", []):
        if sub.get("description"):
            sub["description"] = FILLER_LONG
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- pilote

# fixture -> fonction de scrub
_TARGETS: dict[str, object] = {
    "ethglobal_project.html": scrub_ethglobal,
    "ethglobal_project_ref_desc.html": scrub_ethglobal,
    "ethglobal_showcase.html": scrub_ethglobal,
    "devpost_software.html": scrub_devpost_software,
    "lablab_submissions.json": scrub_lablab_json,
}

# Phrases de PROSE d'origine qui NE doivent plus apparaître après scrub (garde
# anti-régression). On ne liste QUE des fragments de description : les titres de projet
# (« AEGIS GRID »…) sont des métadonnées publiques, légitimement conservées.
_RESIDUES = (
    "decentralized P2P marketplace built on Hedera",  # ethglobal_project (rendu + RSC)
    "AgentIndex is reputation intelligence",  # ethglobal_project_ref_desc
    "Fragility of the Modern World",  # devpost_software
    "increasing atmospheric",  # devpost_software (milieu de prose)
    "autonomous trading agent built for the Kraken",  # lablab_submissions
)


def apply_all() -> None:
    for name, fn in _TARGETS.items():
        path = FIXTURES / name
        text = path.read_text(encoding="utf-8")
        scrubbed = fn(text)  # type: ignore[operator]
        path.write_text(scrubbed, encoding="utf-8")
        print(f"scrub {name}")


def check() -> int:
    bad = []
    for path in FIXTURES.iterdir():
        blob = path.read_text(encoding="utf-8", errors="ignore")
        for residue in _RESIDUES:
            if residue in blob:
                bad.append(f"{path.name}: {residue!r}")
    if bad:
        print("RÉSIDUS de description détectés :", *bad, sep="\n  ", file=sys.stderr)
        return 1
    print("OK : aucun résidu de description intégrale dans les fixtures.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Anonymise les descriptions des fixtures.")
    ap.add_argument("--check", action="store_true", help="vérifie sans modifier")
    args = ap.parse_args(argv)
    if args.check:
        return check()
    apply_all()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
