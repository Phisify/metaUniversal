"""Supabase: post log, settings (token, kill switch), public media storage.

Without SUPABASE_URL the engine still runs in dry-run mode with an empty history.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import settings

log = logging.getLogger(__name__)


class DB:
    def __init__(self):
        self.sb = None
        if settings.supabase_url and settings.supabase_key:
            from supabase import create_client

            self.sb = create_client(settings.supabase_url, settings.supabase_key)

    @property
    def live(self) -> bool:
        return self.sb is not None

    # ---------- posts ----------
    def recent(self, hours: int, statuses=("posted",)) -> list[dict]:
        if not self.live:
            return []
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        res = (
            self.sb.table("posts")
            .select("story_url,story_title,pillar,status,created_at")
            .gte("created_at", since)
            .in_("status", list(statuses))
            .execute()
        )
        return res.data or []

    def pillar_counts_today(self) -> dict:
        if not self.live:
            return {}
        tz = ZoneInfo(settings.timezone)
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        res = (
            self.sb.table("posts").select("pillar").eq("status", "posted").gte("created_at", start.isoformat()).execute()
        )
        counts: dict = {}
        for row in res.data or []:
            counts[row["pillar"]] = counts.get(row["pillar"], 0) + 1
        return counts

    def record(self, **row) -> None:
        if not self.live:
            return
        try:
            self.sb.table("posts").insert(row).execute()
        except Exception as e:
            # If the schema migration hasn't been run yet, still record the post without the new
            # column, otherwise dedupe would miss it and the same story could post twice.
            if "channels" in row:
                log.error("record failed (%s), retrying without channels. Run the schema.sql migration.", e)
                row = {k: v for k, v in row.items() if k != "channels"}
                try:
                    self.sb.table("posts").insert(row).execute()
                    return
                except Exception as e2:
                    e = e2
            log.error("failed to record post: %s", e)

    # ---------- settings ----------
    def get_setting(self, key: str) -> str | None:
        if not self.live:
            return None
        res = self.sb.table("settings").select("value").eq("key", key).limit(1).execute()
        return res.data[0]["value"] if res.data else None

    def set_setting(self, key: str, value: str) -> None:
        if not self.live:
            return
        self.sb.table("settings").upsert(
            {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).execute()

    # ---------- storage ----------
    def upload_jpeg(self, path: str, data: bytes) -> str:
        bucket = self.sb.storage.from_(settings.supabase_bucket)
        bucket.upload(path, data, {"content-type": "image/jpeg", "upsert": "true"})
        return bucket.get_public_url(path).rstrip("?")
