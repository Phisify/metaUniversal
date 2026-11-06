import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass
class Settings:
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY")
    llm_model: str = _env("LLM_MODEL", "claude-sonnet-5-5")

    supabase_url: str = _env("SUPABASE_URL")
    supabase_key: str = _env("SUPABASE_SERVICE_KEY")
    supabase_bucket: str = _env("SUPABASE_BUCKET", "meta-engine")

    ig_user_id: str = _env("IG_USER_ID")
    ig_access_token: str = _env("IG_ACCESS_TOKEN")  # seed only; refreshed copy lives in Supabase
    ig_api_version: str = _env("IG_API_VERSION", "v26.0")

    pixabay_api_key: str = _env("PIXABAY_API_KEY")

    # Cross-posting. Each channel only runs if it is listed in CHANNELS and its keys are set.
    channels: list = field(
        default_factory=lambda: [c.strip() for c in _env("CHANNELS", "ig_story,threads,x,linkedin").split(",") if c.strip()]
    )

    threads_user_id: str = _env("THREADS_USER_ID")
    threads_access_token: str = _env("THREADS_ACCESS_TOKEN")  # seed only; refreshed copy lives in Supabase
    threads_api_base: str = _env("THREADS_API_BASE", "https://graph.threads.net/v1.0")

    x_api_key: str = _env("X_API_KEY")
    x_api_secret: str = _env("X_API_SECRET")
    x_access_token: str = _env("X_ACCESS_TOKEN")
    x_access_secret: str = _env("X_ACCESS_SECRET")
    x_max_chars: int = int(_env("X_MAX_CHARS", "280"))  # raise to 25000 if the account has X Premium

    linkedin_access_token: str = _env("LINKEDIN_ACCESS_TOKEN")  # seed only; refreshed copy lives in Supabase
    linkedin_refresh_token: str = _env("LINKEDIN_REFRESH_TOKEN")
    linkedin_client_id: str = _env("LINKEDIN_CLIENT_ID")
    linkedin_client_secret: str = _env("LINKEDIN_CLIENT_SECRET")
    linkedin_author: str = _env("LINKEDIN_AUTHOR")  # urn:li:organization:123 (company page) or urn:li:person:abc
    linkedin_version: str = _env("LINKEDIN_VERSION", "202606")

    timezone: str = _env("TIMEZONE", "Europe/London")
    post_times: list = field(
        default_factory=lambda: [t.strip() for t in _env("POST_TIMES", "08:30,13:30,19:30").split(",") if t.strip()]
    )
    dry_run: bool = _env("DRY_RUN", "false").lower() == "true"
    contact_email: str = _env("CONTACT_EMAIL", "info@phisify.com")

    out_dir: Path = ROOT / "out"


settings = Settings()


def load_engine_config() -> dict:
    with open(ROOT / "config" / "engine.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


USER_AGENT = f"PhisifyMetaEngine/1.0 (+https://phisify.com; {settings.contact_email})"
