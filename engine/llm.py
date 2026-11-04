"""Thin Claude wrapper that always returns parsed JSON."""
import json
import logging
import re

from anthropic import Anthropic

from .config import settings

log = logging.getLogger(__name__)
_client = None


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


def complete_json(system: str, user: str, max_tokens: int = 2500) -> dict:
    last_err = None
    for attempt in range(2):
        resp = _get_client().messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        try:
            return _parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            log.warning("JSON parse failed (attempt %d): %s", attempt + 1, e)
    raise last_err
