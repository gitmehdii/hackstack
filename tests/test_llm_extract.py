"""Tests de la passe LLM : prompt, parsing, filtrage — client OpenRouter mocké (sans réseau)."""

from __future__ import annotations

import json

import httpx

from pipeline.normalize.llm_extract import (
    LLMExtractor,
    build_system_prompt,
    build_user_prompt,
    parse_response,
)
from pipeline.normalize.taxonomy import load_taxonomy


def test_system_prompt_embeds_taxonomies() -> None:
    tax = load_taxonomy()
    prompt = build_system_prompt(tax)
    assert "Python" in prompt and "GPT-4" in prompt  # tech canonique
    assert "defi" in prompt and "ai-agents" in prompt  # slugs de thèmes
    assert "AT MOST 3" in prompt


def test_user_prompt_truncated() -> None:
    long_desc = "x" * 10000
    prompt = build_user_prompt("Title", "short", long_desc)
    assert len(prompt) <= 4000


def test_parse_response_filters_and_caps() -> None:
    tax = load_taxonomy()
    content = json.dumps(
        {
            "tech_stack": ["Python", "openai", "NotARealTool", "React"],
            "theme_tags": ["defi", "ai-agents", "healthcare", "education", "bogus"],
        }
    )
    tech, themes = parse_response(content, tax)
    assert tech == ["Python", "GPT-4", "React"]  # alias résolu, inconnu retiré
    assert themes == ["defi", "ai-agents", "healthcare"]  # cappé à 3, inconnu retiré


def test_parse_response_handles_garbage() -> None:
    tax = load_taxonomy()
    assert parse_response("not json", tax) == ([], [])
    assert parse_response(json.dumps({"tech_stack": "oops"}), tax) == ([], [])


def test_extractor_end_to_end_mocked() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        answer = json.dumps({"tech_stack": ["python", "react"], "theme_tags": ["defi"]})
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    client = httpx.Client(
        base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler)
    )
    extractor = LLMExtractor(api_key="test", model="test/model", client=client)
    result = extractor.extract("A DeFi lending app", "short", "uses python and react")
    assert result.tech_stack == ["Python", "React"]
    assert result.theme_tags == ["defi"]
    assert result.model == "test/model"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"]["type"] == "json_schema"  # sortie structurée demandée
