"""Fan-out after the Instagram carousel is live: Instagram Story, Threads, X, LinkedIn.

Each channel is independent. One failing never blocks the others or the Instagram post.
A channel only runs if it is listed in CHANNELS and its credentials are set.
"""
import logging
import re
import time
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

from .config import USER_AGENT, settings
from .db import DB
from .instagram import Instagram

log = logging.getLogger(__name__)

THREADS_TOKEN_KEY = "threads_access_token"
LINKEDIN_TOKEN_KEY = "linkedin_access_token"
LINKEDIN_REFRESH_KEY = "linkedin_refresh_token"


class ChannelError(RuntimeError):
    pass


# ---------------------------------------------------------------- text helpers
def fit(parts: list[str], limit: int) -> str:
    """Join non-empty parts with blank lines, dropping from the end until it fits, then hard-trim."""
    parts = [p.strip() for p in parts if p and p.strip()]
    while parts:
        text = "\n\n".join(parts)
        if len(text) <= limit:
            return text
        if len(parts) == 1:
            return text[: limit - 1].rstrip() + "…"
        parts.pop()
    return ""


def short_tags(tags: list[str], n: int) -> str:
    return " ".join(tags[:n])


# ---------------------------------------------------------------- Instagram Story
def post_ig_story(ig: Instagram, story_url: str) -> dict:
    return {"id": ig.publish_story(story_url)}


# ---------------------------------------------------------------- Threads
class Threads:
    def __init__(self, db: DB):
        self.db = db
        self.uid = settings.threads_user_id
        self.base = settings.threads_api_base.rstrip("/")

    @property
    def ready(self) -> bool:
        return bool(self.uid and self.token)

    @property
    def token(self) -> str:
        return self.db.get_setting(THREADS_TOKEN_KEY) or settings.threads_access_token

    def _post(self, path: str, **params) -> dict:
        params["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", params=params, timeout=60)
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in data:
            raise ChannelError(f"threads {path}: {data.get('error', r.text[:300])}")
        return data

    def publish_carousel(self, image_urls: list[str], text: str) -> str:
        children = [
            self._post(f"{self.uid}/threads", media_type="IMAGE", image_url=u, is_carousel_item="true")["id"]
            for u in image_urls[:20]
        ]
        parent = self._post(f"{self.uid}/threads", media_type="CAROUSEL", children=",".join(children), text=text)["id"]
        time.sleep(30)  # Meta recommends ~30s before publishing so uploads finish processing
        return self._post(f"{self.uid}/threads_publish", creation_id=parent)["id"]

    def refresh_token(self) -> None:
        root = self.base.rsplit("/", 1)[0]  # strip the version segment
        r = requests.get(
            f"{root}/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": self.token},
            timeout=30,
        )
        data = r.json()
        if "access_token" not in data:
            raise ChannelError(f"threads token refresh failed: {data}")
        self.db.set_setting(THREADS_TOKEN_KEY, data["access_token"])
        log.info("threads token refreshed")


# ---------------------------------------------------------------- X
class X:
    UPLOAD_V2 = "https://api.x.com/2/media/upload"
    UPLOAD_V1 = "https://upload.twitter.com/1.1/media/upload.json"
    TWEETS = "https://api.x.com/2/tweets"

    def __init__(self):
        self.auth = OAuth1(
            settings.x_api_key, settings.x_api_secret, settings.x_access_token, settings.x_access_secret
        )

    @property
    def ready(self) -> bool:
        return all([settings.x_api_key, settings.x_api_secret, settings.x_access_token, settings.x_access_secret])

    def _upload(self, path: Path) -> str:
        data = path.read_bytes()
        # v2 upload first; the v1.1 endpoint is the fallback while X finishes migrating.
        for url, extra in ((self.UPLOAD_V2, {"media_category": "tweet_image"}), (self.UPLOAD_V1, {})):
            try:
                r = requests.post(url, auth=self.auth, files={"media": (path.name, data, "image/jpeg")}, data=extra, timeout=60)
                if r.status_code < 300:
                    body = r.json()
                    media_id = (body.get("data") or {}).get("id") or body.get("media_id_string")
                    if media_id:
                        return str(media_id)
                log.info("x upload via %s returned %s: %s", url, r.status_code, r.text[:200])
            except Exception as e:
                log.info("x upload via %s failed: %s", url, e)
        raise ChannelError(f"x media upload failed for {path.name}")

    def _tweet(self, text: str, media_ids: list[str], reply_to: str | None = None) -> str:
        body: dict = {"text": text}
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        r = requests.post(self.TWEETS, auth=self.auth, json=body, timeout=30)
        if r.status_code >= 300:
            raise ChannelError(f"x tweet failed {r.status_code}: {r.text[:300]}")
        return r.json()["data"]["id"]

    def publish_thread(self, files: list[Path], first_text: str) -> str:
        """X allows 4 images per post, so slides go out in groups of 4 as a short thread."""
        groups = [files[i : i + 4] for i in range(0, len(files), 4)]
        first_id = reply_to = None
        for n, group in enumerate(groups):
            media_ids = [self._upload(f) for f in group]
            text = first_text if n == 0 else f"{n + 1}/{len(groups)}"
            reply_to = self._tweet(text, media_ids, reply_to)
            first_id = first_id or reply_to
        return first_id


# ---------------------------------------------------------------- LinkedIn
LITTLE_TEXT_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def little_text(text: str) -> str:
    """LinkedIn's Posts API treats these characters as markup unless escaped."""
    return LITTLE_TEXT_RESERVED.sub(r"\\\1", text)


class LinkedIn:
    BASE = "https://api.linkedin.com/rest"

    def __init__(self, db: DB):
        self.db = db
        self.author = settings.linkedin_author

    @property
    def ready(self) -> bool:
        return bool(self.author and self.token)

    @property
    def token(self) -> str:
        return self.db.get_setting(LINKEDIN_TOKEN_KEY) or settings.linkedin_access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "LinkedIn-Version": settings.linkedin_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "User-Agent": USER_AGENT,
        }

    def _upload(self, path: Path) -> str:
        r = requests.post(
            f"{self.BASE}/images?action=initializeUpload",
            headers=self._headers(),
            json={"initializeUploadRequest": {"owner": self.author}},
            timeout=30,
        )
        if r.status_code >= 300:
            raise ChannelError(f"linkedin initializeUpload {r.status_code}: {r.text[:300]}")
        value = r.json()["value"]
        put = requests.put(
            value["uploadUrl"],
            headers={"Authorization": f"Bearer {self.token}"},
            data=path.read_bytes(),
            timeout=60,
        )
        if put.status_code >= 300:
            raise ChannelError(f"linkedin image upload {put.status_code}: {put.text[:300]}")
        return value["image"]

    def publish_multi_image(self, files: list[Path], text: str, alt: str) -> str:
        images = [{"id": self._upload(f), "altText": alt[:120]} for f in files[:20]]
        body = {
            "author": self.author,
            "commentary": little_text(text),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": {"multiImage": {"images": images}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = requests.post(f"{self.BASE}/posts", headers=self._headers(), json=body, timeout=60)
        if r.status_code >= 300:
            raise ChannelError(f"linkedin post {r.status_code}: {r.text[:300]}")
        return r.headers.get("x-restli-id", "")

    def refresh_token(self) -> None:
        refresh = self.db.get_setting(LINKEDIN_REFRESH_KEY) or settings.linkedin_refresh_token
        if not (refresh and settings.linkedin_client_id and settings.linkedin_client_secret):
            log.info("linkedin: no refresh token configured, token must be renewed by hand every 60 days")
            return
        r = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            timeout=30,
        )
        data = r.json()
        if "access_token" not in data:
            raise ChannelError(f"linkedin token refresh failed: {data}")
        self.db.set_setting(LINKEDIN_TOKEN_KEY, data["access_token"])
        if data.get("refresh_token"):
            self.db.set_setting(LINKEDIN_REFRESH_KEY, data["refresh_token"])
        log.info("linkedin token refreshed, expires in %s days", int(data.get("expires_in", 0)) // 86400)


# ---------------------------------------------------------------- fan-out
def channel_texts(draft: dict, tags: list[str], source_name: str) -> dict:
    headline = draft.get("caption_headline") or f"{draft['cover_title']}: {draft['cover_subtitle']}"
    body = draft.get("caption_body", "")
    src = f"Source: {source_name}"
    return {
        "headline": headline,
        "threads": fit([headline, body, src, short_tags(tags, 1)], 500),
        "x": fit([headline, src, short_tags(tags, 2)], settings.x_max_chars),
        "linkedin": fit([headline, body, src, short_tags(tags, 4)], 3000),
    }


def fan_out(
    db: DB,
    ig: Instagram,
    *,
    files: list[Path],
    image_urls: list[str],
    story_url: str,
    draft: dict,
    tags: list[str],
    source_name: str,
) -> dict:
    enabled = set(settings.channels)
    texts = channel_texts(draft, tags, source_name)
    results: dict = {}

    def attempt(name: str, fn):
        try:
            results[name] = {"ok": True, **fn()}
            log.info("cross-posted to %s", name)
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:500]}
            log.error("cross-post to %s failed: %s", name, e)

    if "ig_story" in enabled and story_url:
        attempt("ig_story", lambda: post_ig_story(ig, story_url))

    if "threads" in enabled:
        th = Threads(db)
        if th.ready:
            attempt("threads", lambda: {"id": th.publish_carousel(image_urls, texts["threads"])})

    if "x" in enabled:
        x = X()
        if x.ready:
            attempt("x", lambda: {"id": x.publish_thread(files, texts["x"])})

    if "linkedin" in enabled:
        li = LinkedIn(db)
        if li.ready:
            attempt("linkedin", lambda: {"id": li.publish_multi_image(files, texts["linkedin"], texts["headline"])})

    return results
