import os
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
    task_soft_time_limit=90,        # task gets SoftTimeLimitExceeded at 90 s
    task_time_limit=120,            # hard kill at 120 s
    worker_prefetch_multiplier=1,   # fair dispatch — don't pre-fetch more than 1
    task_acks_late=True,            # ack only after task completes (safe retry)
    worker_max_tasks_per_child=200, # recycle workers to prevent memory leaks
)
