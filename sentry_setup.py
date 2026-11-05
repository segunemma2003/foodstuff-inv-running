"""Sentry error, warning, performance and release-health monitoring.

No-op unless SENTRY_DSN is set, so local dev and tests are unaffected.
FastAPI/Starlette, SQLAlchemy, httpx, Redis and Celery integrations are
enabled automatically when those packages are installed.

What gets reported:
  * every unhandled exception (100% - errors are never sampled)
  * every logger.warning / logger.error / logger.exception call as an issue
  * Python `warnings.warn(...)` (routed through logging)
  * release health: crash-free sessions per deploy (needs a release, see below)
  * performance traces for SENTRY_TRACES_SAMPLE_RATE of requests

Env vars:
  SENTRY_DSN                 required to enable
  SENTRY_ENVIRONMENT         default "production"
  SENTRY_RELEASE             default HEROKU_SLUG_COMMIT (enable with
                             `heroku labs:enable runtime-dyno-metadata`)
  SENTRY_TRACES_SAMPLE_RATE  default 0.2 (20% of requests traced)
"""
import logging
import os

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration


def init_sentry(component: str) -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return

    logging.captureWarnings(True)
    integrations = [
        # INFO+ logs become breadcrumbs; WARNING+ logs become Sentry issues
        LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
    ]

    from sentry_sdk.integrations.celery import CeleryIntegration

    # monitor_beat_tasks: every Celery Beat schedule shows up as a Sentry Cron
    # Monitor, so missed/failed/slow scheduled jobs raise alerts.
    integrations.append(CeleryIntegration(monitor_beat_tasks=True))

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or os.getenv("HEROKU_SLUG_COMMIT") or None,
        integrations=integrations,
        sample_rate=1.0,  # send every error/warning event
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2")),
        send_default_pii=False,
    )
    sentry_sdk.get_global_scope().set_tag("component", component)
