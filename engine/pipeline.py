"""One run = one carousel. Fetch -> pick -> write -> check -> photo -> render -> publish -> log."""
import logging
import uuid
from datetime import datetime, timezone

from rapidfuzz import fuzz

from . import editor
from .config import load_engine_config, settings
from .db import DB
from .images import find_photo
from .instagram import Instagram
from .render import build_pages, render
from .sources import extract_article, fetch_feeds, market_snapshot

log = logging.getLogger(__name__)
MIN_SOURCE_CHARS = 600  # below this we cannot fact-check, so we skip the story
MAX_DRAFTS = 3     # LLM-costly attempts per run
MAX_SCAN = 10      # stories looked at per run (blocked ones are free)


def _priority_pillar(mix: dict, counts: dict) -> str:
    total_after = sum(counts.values()) + 1
    deficits = {p: share * total_after - counts.get(p, 0) for p, share in mix.items()}
    return max(deficits, key=deficits.get)


def _caption(draft: dict, cfg: dict, source_name: str, credit: str) -> str:
    tags, seen = [], set()
    for t in cfg.get("hashtags_always", []) + draft.get("hashtags", []):
        t = "#" + t.lstrip("#").replace(" ", "")
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    tags = tags[:6]
    headline = draft.get("caption_headline") or f"{draft['cover_title']}: {draft['cover_subtitle']}"
    parts = [
        headline,
        draft.get("caption_body", ""),
        cfg["cta_line"],
        f"Source: {source_name}" + (f"\n{credit}" if credit else ""),
        " ".join(tags),
    ]
    return editor.kill_dashes("\n\n".join(p for p in parts if p))[:2200]


def run(dry_run: bool | None = None) -> dict:
    dry_run = settings.dry_run if dry_run is None else dry_run
    cfg = load_engine_config()
    db = DB()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    if db.get_setting("paused") == "true":
        log.info("engine paused via settings table, skipping run")
        return {"status": "paused"}
    if not dry_run and not db.live:
        raise RuntimeError("live posting needs SUPABASE_URL and SUPABASE_SERVICE_KEY (media hosting + dedupe)")

    ig = Instagram(db)
    if not dry_run and ig.quota_left() < 2:
        log.warning("instagram publishing quota nearly used, skipping run")
        return {"status": "quota"}

    # 1. ingest + dedupe
    stories = fetch_feeds(cfg["feeds"], cfg["max_story_age_hours"])
    history = db.recent(cfg["dedupe_window_hours"], statuses=("posted", "rejected", "dry_run", "failed"))
    used_urls = {h["story_url"] for h in history}
    posted_titles = [h["story_title"] for h in history if h["status"] == "posted"]
    cutoff = cfg["title_similarity_cutoff"]
    candidates = [
        s
        for s in stories
        if s.url not in used_urls
        and not any(fuzz.token_set_ratio(s.title, t) >= cutoff for t in posted_titles)
    ][:60]
    if not candidates:
        log.info("no fresh candidates")
        return {"status": "no_candidates"}

    # 2. pick
    priority = _priority_pillar(cfg["mix"], db.pillar_counts_today())
    ranked = editor.select(candidates, posted_titles[-40:], priority)
    market = market_snapshot()

    # 3. write + check, falling back down the ranking
    drafts = 0
    for idx in ranked[:MAX_SCAN]:
        if drafts >= MAX_DRAFTS:
            break
        story = candidates[idx]
        article = extract_article(story.url)
        if len(article) < MIN_SOURCE_CHARS and len(story.content) > len(article):
            article = story.content
            log.info("using feed text for: %s (%d chars)", story.title, len(article))
        if len(article) < MIN_SOURCE_CHARS:
            log.info("skip (source too thin to verify): %s", story.title)
            db.record(story_url=story.url, story_title=story.title, source=story.source,
                      pillar=story.pillar, status="rejected", reason="source text too thin")
            continue

        drafts += 1
        draft = editor.write(story, article, market, cfg["webinar_themes"])
        ok, issues = editor.check(draft, article, market)
        if not ok and issues:
            log.info("check failed, revising once: %s", issues)
            draft = editor.revise(draft, issues, article, market, cfg["webinar_themes"])
            ok, issues = editor.check(draft, article, market)
        if not ok:
            log.info("check failed for %s: %s", story.title, issues)
            db.record(story_url=story.url, story_title=story.title, source=story.source,
                      pillar=draft.get("pillar", story.pillar), status="rejected",
                      reason="; ".join(issues)[:1000], payload=draft)
            continue

        # 4. photo + render
        photo = find_photo(draft.get("entity_query", ""), draft.get("scene_query", ""), draft.get("entity_type", "other"), draft.get("entity_context", ""))
        pages = build_pages(draft, photo, cfg["brand"], story.source)
        out_dir = settings.out_dir / run_id
        files = render(pages, out_dir)
        caption = _caption(draft, cfg, story.source, photo.credit if photo else "")
        (out_dir / "caption.txt").write_text(caption, encoding="utf-8")
        pillar = draft.get("pillar") if draft.get("pillar") in cfg["mix"] else story.pillar

        if dry_run:
            log.info("DRY RUN: rendered %d slides to %s", len(files), out_dir)
            db.record(story_url=story.url, story_title=story.title, source=story.source,
                      pillar=pillar, status="dry_run", payload=draft)
            return {"status": "dry_run", "dir": str(out_dir), "story": story.title}

        # 5. publish
        try:
            urls = [db.upload_jpeg(f"{run_id}/{f.name}", f.read_bytes()) for f in files]
            media_id = ig.publish_carousel(urls, caption)
        except Exception as e:
            log.error("publish failed: %s", e)
            db.record(story_url=story.url, story_title=story.title, source=story.source,
                      pillar=pillar, status="failed", reason=str(e)[:1000], payload=draft)
            return {"status": "failed", "error": str(e)}

        db.record(story_url=story.url, story_title=story.title, source=story.source, pillar=pillar,
                  status="posted", ig_media_id=media_id, payload={**draft, "caption": caption, "images": urls})
        return {"status": "posted", "media_id": media_id, "story": story.title}

    log.info("no story passed checks this run")
    return {"status": "nothing_passed"}
