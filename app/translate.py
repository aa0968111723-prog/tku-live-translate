from __future__ import annotations

import os
from typing import Any

import httpx

from . import glossary

OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "unused"
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "llama-3.3-70b-versatile"
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or ""
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

SYSTEM_PROMPT = """You are a live classroom caption translator.

Translate one spoken Mandarin utterance into a single natural English caption.

Rules:
- Output English only. No preface, no notes, no bullet list.
- One short caption, spoken-lecture style. Do not expand into a paragraph.
- Do not explain, teach, or add content the speaker did not say.
- If the source is a fragment or filler, translate the fragment.
- If a glossary is provided, you MUST use the specified English for those source terms and their aliases. Do not paraphrase locked terms.
- Traditional and simplified characters may appear; treat aliases as the same term when listed.
- Keep numbers and durations as spoken.
- Glossary (may be empty):
{glossary_table}
"""


def available() -> bool:
    return bool(OPENAI_BASE_URL or GROQ_API_KEY)


def _glossary_table() -> str:
    rows = glossary.terms()
    if not rows:
        return "(empty glossary — translate naturally)"
    lines = ["zh | aliases | en | lock"]
    for item in rows:
        aliases = ", ".join(str(a) for a in (item.get("aliases") or []) if a) or "-"
        lock = "true" if item.get("lock", True) else "false"
        lines.append(
            f"{item.get('zh', '')} | {aliases} | {item.get('en', '')} | {lock}"
        )
    return "\n".join(lines)


def _endpoints() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if OPENAI_BASE_URL:
        out.append((OPENAI_BASE_URL, OPENAI_API_KEY or "unused"))
    if GROQ_API_KEY:
        out.append((GROQ_BASE_URL, GROQ_API_KEY))
    return out


async def _chat(base_url: str, api_key: str, zh: str) -> str:
    payload: dict[str, Any] = {
        "model": OPENAI_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(glossary_table=_glossary_table()),
            },
            {"role": "user", "content": zh},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    )
    return str(content).strip().strip('"').strip()


async def translate(zh: str) -> str:
    text = (zh or "").strip()
    if not text:
        return ""
    last_error: Exception | None = None
    for base_url, api_key in _endpoints():
        try:
            en = await _chat(base_url, api_key, text)
            if en:
                return glossary.apply_locked(en, text)
        except Exception as exc:  # noqa: BLE001 — caption path must not kill the socket
            last_error = exc
            continue
    if last_error:
        return glossary.apply_locked(text, text)
    return glossary.apply_locked(text, text)
