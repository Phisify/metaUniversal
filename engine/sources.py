"""Story ingestion: RSS feeds, article text, market snapshot."""
import html
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import trafilatura

from .config import USER_AGENT

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


@dataclass
class Story:
    title: str
    url: str
    source: str
    pillar: str
    published: str  # ISO UTC
    summary: str

    def to_dict(self):
        return asdict(self)


def fetch_feeds(feeds: list, max_age_hours: int) -> list[Story]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    stories: list[Story] = []
    seen_urls = set()
    for feed in feeds:
        try:
            resp = requests.get(feed["url"], headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:  # one bad feed never stops the run
            log.warning("feed failed %s: %s", feed["name"], e)
            continue
        for entry in parsed.entries[:40]:
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            if not stamp:
                continue
            published = datetime(*stamp[:6], tzinfo=timezone.utc)
            if published < cutoff:
                continue
            url = (entry.get("link") or "").split("?utm")[0]
            title = strip_html(entry.get("title", ""))
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            stories.append(
                Story(
                    title=title,
                    url=url,
                    source=feed["name"],
                    pillar=feed["pillar"],
                    published=published.isoformat(),
                    summary=strip_html(entry.get("summary", ""))[:500],
                )
            )
    log.info("fetched %d fresh stories from %d feeds", len(stories), len(feeds))
    return stories


def extract_article(url: str) -> str:
    """Full article text for grounding and fact-checking. Empty string if blocked."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if resp.status_code >= 400:
            return ""
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False) or ""
        return text[:9000]
    except Exception as e:
        log.warning("article extract failed %s: %s", url, e)
        return ""


def market_snapshot() -> dict:
    """Live prices the writer may quote. Anything not here or in the article is off limits."""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin,ethereum,solana",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            coin: {"usd": round(v["usd"], 2), "change_24h_pct": round(v.get("usd_24h_change", 0.0), 2)}
            for coin, v in data.items()
        }
    except Exception as e:
        log.warning("market snapshot failed: %s", e)
        return {}
