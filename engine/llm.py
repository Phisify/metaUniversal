"""Thin Claude wrapper that always returns parsed JSON."""
import json
import logging
import re

from anthropic import Anthropic

from .config import settings

log = logging.getLogger(__name__)
_client = None

# Newer models can spend part of the budget thinking before they write.
# A low max_tokens can be used up before any text appears, so keep a generous floor.
MIN_TOKENS = 8000


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    return json.loads(match.group(0))


def complete_json(system: str, user, max_tokens: int = 2500) -> dict:
    """`user` is a string, or a list of content blocks (text + images)."""
    last_err = None
    for attempt in range(2):
        resp = _get_client().messages.create(
            model=settings.llm_model,
            max_tokens=max(max_tokens, MIN_TOKENS),
            system=system + "\n\nRespond with the JSON object only. No preamble, no code fences.",
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        try:
            return _parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            log.warning(
                "JSON parse failed (attempt %d): stop_reason=%s blocks=%s text=%r",
                attempt + 1,
                resp.stop_reason,
                [b.type for b in resp.content],
                text[:300],
            )
    raise last_err
