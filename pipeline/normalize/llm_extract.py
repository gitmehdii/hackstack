"""Passe LLM de l'extraction (Étape 4) : tech_stack ET theme_tags depuis la description.

OpenRouter, sortie structurée (JSON schema), taxonomies fermées injectées dans le prompt.
La sortie du modèle est re-filtrée côté client (`Taxonomy.clean_tech` / `clean_themes`) :
défense en profondeur, on ne fait jamais confiance au modèle pour rester dans le
vocabulaire ni pour respecter le cap de 3 thèmes.

Couche HTTP isolée (injectable) pour tester sans réseau (cf. PROJECT.md : jamais d'appel
réseau en test). Utilisée seulement quand la passe GitHub n'a pas donné de stack fiable
(devpost/lablab, ethglobal sans repo) et, pour les thèmes, sur tout le corpus.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from pipeline.normalize.taxonomy import Taxonomy, load_taxonomy

DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
_MAX_INPUT_CHARS = 4000  # descriptions tronquées : le signal utile est en tête

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tech_stack": {"type": "array", "items": {"type": "string"}},
        "theme_tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tech_stack", "theme_tags"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LLMResult:
    tech_stack: list[str]
    theme_tags: list[str]
    model: str


def build_system_prompt(tax: Taxonomy) -> str:
    tech = ", ".join(tax.tech_canonical)
    themes = "\n".join(f"  - {t.slug}: {t.label} — {t.description}" for t in tax.themes)
    return (
        "You label hackathon projects. Read the project text and return JSON.\n\n"
        "`tech_stack`: technologies actually used, ONLY from this closed list "
        "(exact strings, omit anything not in the list):\n"
        f"{tech}\n\n"
        "`theme_tags`: AT MOST 3 theme slugs, ONLY from this closed list "
        "(use the slug, the part before the colon), ordered most to least relevant:\n"
        f"{themes}\n\n"
        "Return only values you are confident about. Empty arrays are fine. "
        "Never invent values outside the lists."
    )


def build_user_prompt(title: str, short: str | None, description: str | None) -> str:
    parts = [f"Title: {title}"]
    if short:
        parts.append(f"Summary: {short}")
    if description:
        parts.append(f"Description: {description}")
    text = "\n".join(parts)
    return text[:_MAX_INPUT_CHARS]


def parse_response(content: str, tax: Taxonomy) -> tuple[list[str], list[str]]:
    """Extrait (tech_stack, theme_tags) filtrés sur la taxonomie depuis la réponse JSON."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return [], []
    raw_tech = data.get("tech_stack") or []
    raw_themes = data.get("theme_tags") or []
    tech = tax.clean_tech([str(x) for x in raw_tech]) if isinstance(raw_tech, list) else []
    themes = tax.clean_themes([str(x) for x in raw_themes]) if isinstance(raw_themes, list) else []
    return tech, themes


class LLMExtractor:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        self._model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
        self._tax = load_taxonomy()
        self._system = build_system_prompt(self._tax)
        self._client = client or httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://github.com/gitmehdii/hackstack",
                "X-Title": "hackstack",
            },
            timeout=60.0,
        )

    def extract(self, title: str, short: str | None, description: str | None) -> LLMResult:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": build_user_prompt(title, short, description)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
        }
        resp = self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        # Certains modèles renvoient parfois `content` null (ou une forme inattendue) :
        # on retombe alors sur des listes vides plutôt que de casser le run.
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        tech, themes = parse_response(content or "", self._tax)
        return LLMResult(tech_stack=tech, theme_tags=themes, model=self._model)
