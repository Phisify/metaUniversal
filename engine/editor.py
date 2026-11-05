"""Select, write and fact-check one carousel."""
import json
import logging
import re

from . import prompts
from .llm import complete_json
from .sources import Story

log = logging.getLogger(__name__)

DASHES = re.compile(r"\s*[—–]\s*")


def kill_dashes(text: str) -> str:
    # Belt and braces on top of the prompt rule. Ranges like "3.75%–4.00%" become "3.75% to 4.00%".
    text = re.sub(r"(\d[%\w]*)\s*[–—]\s*(\d)", r"\1 to \2", text)
    return DASHES.sub(", ", text)


def sanitize(obj):
    if isinstance(obj, str):
        return kill_dashes(obj).strip()
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    return obj


def select(candidates: list[Story], recent_titles: list[str], priority_pillar: str) -> list[int]:
    listing = [
        {"index": i, "title": s.title, "source": s.source, "pillar": s.pillar, "summary": s.summary[:280]}
        for i, s in enumerate(candidates)
    ]
    user = (
        f"PRIORITY PILLAR: {priority_pillar}\n\n"
        f"RECENTLY POSTED:\n{json.dumps(recent_titles, ensure_ascii=False)}\n\n"
        f"CANDIDATES:\n{json.dumps(listing, ensure_ascii=False)}"
    )
    out = complete_json(prompts.SELECT_SYSTEM, user, max_tokens=400)
    ranked = [i for i in out.get("ranked", []) if isinstance(i, int) and 0 <= i < len(candidates)]
    log.info("editor picked %s: %s", ranked, out.get("why", ""))
    return ranked


def write(story: Story, article_text: str, market: dict, themes: list[str]) -> dict:
    user = (
        f"WEBINAR THEMES (pick one):\n{json.dumps(themes)}\n\n"
        f"STORY: {story.title}\nOUTLET: {story.source}\nFEED PILLAR: {story.pillar}\n\n"
        f"MARKET SNAPSHOT (USD, live):\n{json.dumps(market)}\n\n"
        f"SOURCE TEXT:\n{article_text}"
    )
    draft = sanitize(complete_json(prompts.WRITE_SYSTEM, user, max_tokens=2500))
    return _tidy(draft, themes)


def _tidy(draft: dict, themes: list[str]) -> dict:
    if draft.get("theme") not in themes:
        draft["theme"] = ""
    draft["slides"] = [s for s in draft.get("slides", []) if s.get("heading") and s.get("body")][:4]
    return draft


def revise(draft: dict, issues: list[str], article_text: str, market: dict, themes: list[str]) -> dict:
    user = (
        f"ISSUES:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
        f"MARKET SNAPSHOT:\n{json.dumps(market)}\n\n"
        f"SOURCE TEXT:\n{article_text}\n\n"
        f"DRAFT:\n{json.dumps(draft, ensure_ascii=False, indent=1)}"
    )
    fixed = sanitize(complete_json(prompts.REVISE_SYSTEM, user, max_tokens=2500))
    for key in ("entity_query", "entity_type", "entity_context", "scene_query", "pillar"):
        fixed.setdefault(key, draft.get(key, ""))
    return _tidy(fixed, themes)


def check(draft: dict, article_text: str, market: dict) -> tuple[bool, list[str]]:
    # Hard checks first: cheap and deterministic.
    issues = []
    if not draft.get("cover_title") or not draft.get("cover_subtitle"):
        issues.append("missing cover text")
    if len(draft.get("slides", [])) < 3:
        issues.append("fewer than 3 slides")
    if len(draft.get("cover_subtitle", "").split()) > 16:
        issues.append("subtitle too long")
    if issues:
        return False, issues

    user = (
        f"MARKET SNAPSHOT:\n{json.dumps(market)}\n\n"
        f"SOURCE TEXT:\n{article_text}\n\n"
        f"DRAFT:\n{json.dumps(draft, ensure_ascii=False, indent=1)}"
    )
    out = complete_json(prompts.CHECK_SYSTEM, user, max_tokens=600)
    return bool(out.get("pass")), out.get("issues", [])
