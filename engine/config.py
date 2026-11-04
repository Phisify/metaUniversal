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

    pexels_api_key: str = _env("PEXELS_API_KEY")

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
