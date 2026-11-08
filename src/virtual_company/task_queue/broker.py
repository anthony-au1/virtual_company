"""Shared Redis Streams broker configuration."""

from taskiq_redis import RedisStreamBroker

from virtual_company.config import get_settings

settings = get_settings()

broker = RedisStreamBroker(
    url=settings.taskiq_redis_url,
    queue_name=settings.taskiq_stream_name,
    consumer_group_name=settings.taskiq_consumer_group,
    idle_timeout=settings.taskiq_idle_timeout_ms,
    unacknowledged_lock_timeout=settings.taskiq_reclaim_lock_timeout_seconds,
)
