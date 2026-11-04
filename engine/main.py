"""Entry point.

  python -m engine.main run            one carousel now (respects DRY_RUN)
  python -m engine.main run --dry      render only, never publish
  python -m engine.main schedule       run forever on POST_TIMES + weekly token refresh
  python -m engine.main refresh-token  refresh the Instagram token now
  python -m engine.main pause|resume   kill switch (stored in Supabase)
"""
import argparse
import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from .db import DB
from .instagram import Instagram
from .pipeline import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("engine")


def safe_run():
    try:
        log.info("run result: %s", run())
    except Exception:
        log.exception("run crashed")  # never kill the scheduler


def safe_refresh():
    try:
        Instagram(DB()).refresh_token()
    except Exception:
        log.exception("token refresh failed")


def schedule():
    sched = BlockingScheduler(timezone=settings.timezone)
    for t in settings.post_times:
        hour, minute = t.split(":")
        sched.add_job(safe_run, CronTrigger(hour=int(hour), minute=int(minute), timezone=settings.timezone),
                      misfire_grace_time=1800, coalesce=True, max_instances=1)
    sched.add_job(safe_refresh, CronTrigger(day_of_week="mon", hour=3, minute=10, timezone=settings.timezone))
    log.info("scheduler up: posts at %s %s, dry_run=%s", settings.post_times, settings.timezone, settings.dry_run)
    sched.start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "schedule", "refresh-token", "pause", "resume"])
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    if args.command == "run":
        print(run(dry_run=True if args.dry else None))
    elif args.command == "schedule":
        schedule()
    elif args.command == "refresh-token":
        Instagram(DB()).refresh_token()
    elif args.command in ("pause", "resume"):
        DB().set_setting("paused", "true" if args.command == "pause" else "false")
        print(f"engine {args.command}d")


if __name__ == "__main__":
    main()
