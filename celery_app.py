import os
import ssl
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "foodstuff",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["utils.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=7200,            # results kept 2 hours in Redis
    # Default caps for short tasks (email, PDF). Bulk Excel tasks in utils/tasks.py
    # override with soft_time_limit=900 / time_limit=960 (15 min).
    task_soft_time_limit=90,
    task_time_limit=120,
    worker_prefetch_multiplier=1,   # fair dispatch — don't pre-fetch more than 1
    task_acks_late=True,            # ack only after task completes (safe retry)
    worker_max_tasks_per_child=200, # recycle workers to prevent memory leaks
)

# Heroku Redis uses rediss:// (TLS). Celery requires ssl_cert_reqs to be set
# explicitly — without it the worker refuses to start.
if REDIS_URL.startswith("rediss://"):
    _ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
    celery_app.conf.update(
        broker_use_ssl=_ssl,
        redis_backend_use_ssl=_ssl,
    )
