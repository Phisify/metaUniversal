"""Instagram API with Instagram Login: carousel publishing and token refresh."""
import logging
import time

import requests

from .config import settings
from .db import DB

log = logging.getLogger(__name__)
BASE = f"https://graph.instagram.com/{settings.ig_api_version}"
TOKEN_KEY = "ig_access_token"


class IGError(RuntimeError):
    pass


class Instagram:
    def __init__(self, db: DB):
        self.db = db
        self.uid = settings.ig_user_id

    @property
    def token(self) -> str:
        return self.db.get_setting(TOKEN_KEY) or settings.ig_access_token

    def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        r = requests.request(method, f"{BASE}/{path}", params=params, timeout=60)
        try:
            data = r.json()
        except ValueError:
            raise IGError(f"{r.status_code} {r.text[:300]}")
        if r.status_code >= 400 or "error" in data:
            raise IGError(str(data.get("error", data)))
        return data

    def quota_left(self) -> int:
        data = self._call("GET", f"{self.uid}/content_publishing_limit", fields="quota_usage,config")
        row = (data.get("data") or [{}])[0]
        total = row.get("config", {}).get("quota_total", 50)
        return total - row.get("quota_usage", 0)

    def _wait_ready(self, container_id: str, timeout_s: int = 120) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self._call("GET", container_id, fields="status_code").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise IGError(f"container {container_id} status {status}")
            time.sleep(3)
        raise IGError(f"container {container_id} not ready after {timeout_s}s")

    def publish_carousel(self, image_urls: list[str], caption: str) -> str:
        children = []
        for url in image_urls:
            cid = self._call("POST", f"{self.uid}/media", image_url=url, is_carousel_item="true")["id"]
            children.append(cid)
        for cid in children:
            self._wait_ready(cid)
        parent = self._call(
            "POST", f"{self.uid}/media", media_type="CAROUSEL", children=",".join(children), caption=caption
        )["id"]
        self._wait_ready(parent)
        media_id = self._call("POST", f"{self.uid}/media_publish", creation_id=parent)["id"]
        log.info("published carousel %s", media_id)
        return media_id

    def refresh_token(self) -> None:
        """Long-lived tokens last 60 days. Refreshing weekly keeps the engine alive indefinitely."""
        r = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": self.token},
            timeout=30,
        )
        data = r.json()
        if "access_token" not in data:
            raise IGError(f"token refresh failed: {data}")
        self.db.set_setting(TOKEN_KEY, data["access_token"])
        log.info("instagram token refreshed, expires in %s days", int(data.get("expires_in", 0)) // 86400)
