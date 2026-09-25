from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GLOSSARY_PATH = Path(os.getenv("GLOSSARY_PATH", "data/glossary.json"))

# Minimal mapping used only when matching aliases; not a term list.
_SIMP_TO_TRAD = str.maketrans(
    "会学观经数开静禅语头打坐行话"
    "會學觀經數開靜禪語頭打坐行話"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty() -> dict[str, Any]:
    return {"updated_at": _now(), "terms": []}


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).translate(_SIMP_TO_TRAD).casefold()


def _term_keys(item: dict[str, Any]) -> list[str]:
    keys = [str(item.get("zh") or "")]
    keys.extend(str(a) for a in (item.get("aliases") or []) if a)
    return [k for k in keys if k]


def load() -> dict[str, Any]:
    if not GLOSSARY_PATH.exists():
        data = _empty()
        save(data)
        return data
    try:
        raw = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    terms = raw.get("terms")
    if not isinstance(terms, list):
        terms = []
    return {
        "updated_at": raw.get("updated_at") or _now(),
        "terms": [t for t in terms if isinstance(t, dict) and t.get("zh")],
    }


def save(data: dict[str, Any]) -> None:
    GLOSSARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": data.get("updated_at") or _now(),
        "terms": data.get("terms") or [],
    }
    tmp = GLOSSARY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(GLOSSARY_PATH)


def terms() -> list[dict[str, Any]]:
    return list(load().get("terms") or [])


def upsert(item: dict[str, Any]) -> dict[str, Any]:
    zh = str(item.get("zh") or "").strip()
    if not zh:
        raise ValueError("zh is required")
    incoming = {
        "zh": zh,
        "en": str(item.get("en") or "").strip(),
        "aliases": [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()],
        "lock": bool(item.get("lock", True)),
        "cat": str(item.get("cat") or "term").strip() or "term",
    }
    data = load()
    found = False
    for idx, old in enumerate(data["terms"]):
        if str(old.get("zh") or "").strip() == zh:
            data["terms"][idx] = incoming
            found = True
            break
    if not found:
        data["terms"].append(incoming)
    data["updated_at"] = _now()
    save(data)
    return data


def normalize_zh(text: str) -> str:
    out = (text or "").strip()
    if not out:
        return ""
    pairs: list[tuple[str, str]] = []
    for item in terms():
        std = str(item.get("zh") or "").strip()
        if not std:
            continue
        for key in _term_keys(item):
            pairs.append((key, std))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    folded_out = _fold(out)
    for key, std in pairs:
        folded_key = _fold(key)
        if not folded_key:
            continue
        if key in out:
            out = out.replace(key, std)
            folded_out = _fold(out)
        elif folded_key in folded_out:
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            out = pattern.sub(std, out)
            folded_out = _fold(out)
    return out.strip()


def apply_locked(en: str, zh: str) -> str:
    result = (en or "").strip()
    source = zh or ""
    if not source:
        return result
    folded_src = _fold(source)
    for item in terms():
        if not item.get("lock", True):
            continue
        locked_en = str(item.get("en") or "").strip()
        if not locked_en:
            continue
        hit = False
        for key in _term_keys(item):
            if key and (key in source or _fold(key) in folded_src):
                hit = True
                break
        if not hit:
            continue
        if locked_en.casefold() in result.casefold():
            continue
        leaked = False
        for key in _term_keys(item):
            if key and key in result:
                result = result.replace(key, locked_en)
                leaked = True
        if not leaked or locked_en.casefold() not in result.casefold():
            result = (result + f" ({locked_en})").strip()
    return result.strip()
