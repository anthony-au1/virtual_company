"""Focused tests for Taskiq infrastructure without Redis or database access."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from taskiq import TaskiqEvents
from taskiq.result_backends.dummy import DummyResultBackend

from virtual_company.task_queue import tasks
from virtual_company.task_queue.broker import broker


def test_broker_uses_configured_stream_and_no_retry_or_redis_result_backend() -> None:
    assert broker.queue_name == "virtual-company-tasks"
    assert broker.consumer_group_name == "virtual-company-workers"
    assert broker.idle_timeout == 86_400_000
    assert broker.unacknowledged_lock_timeout == 30
    assert isinstance(broker.result_backend, DummyResultBackend)
    assert not broker.middlewares


def test_probe_is_registered_with_explicit_acknowledgement_and_no_retry() -> None:
    assert tasks.infrastructure_probe.task_name in broker.get_all_tasks()
    assert tasks.infrastructure_probe.labels["ack_type"] == "when_executed"
    assert "retry_on_error" not in tasks.infrastructure_probe.labels


@pytest.mark.asyncio
async def test_probe_emits_safe_events_and_returns_serializable_result(caplog) -> None:
    with caplog.at_level("INFO", logger="virtual_company.observability.runtime"):
        result = await tasks.infrastructure_probe.original_func("probe-123")

    assert result == {"probe_id": "probe-123", "status": "COMPLETED"}
    assert "taskiq_probe_started" in caplog.text
    assert "taskiq_probe_completed" in caplog.text
    probe_records = [record for record in caplog.records if record.name.endswith("runtime")]
    assert all(record.context["probe_id"] == "probe-123" for record in probe_records)


@pytest.mark.asyncio
async def test_probe_rejects_invalid_sleep_duration() -> None:
    with pytest.raises(ValueError, match="sleep_seconds"):
        await tasks.infrastructure_probe.original_func("probe-123", 301)


@pytest.mark.asyncio
async def test_worker_observability_hooks_initialize_and_shutdown(monkeypatch, caplog) -> None:
    observability = Mock()
    configure = Mock()
    shutdown = Mock()
    monkeypatch.setattr(tasks, "configure_observability", configure)
    monkeypatch.setattr(tasks, "get_observability", lambda: observability)
    monkeypatch.setattr(tasks, "shutdown_observability", shutdown)

    with caplog.at_level("INFO", logger="virtual_company.task_queue.tasks"):
        await tasks.on_worker_startup(None)
        await tasks.on_worker_shutdown(None)

    configure.assert_called_once()
    observability.clear_context.assert_called_once()
    shutdown.assert_called_once()
    assert "taskiq_worker_started" in caplog.text
    assert "taskiq_worker_stopped" in caplog.text


def test_worker_lifecycle_hooks_are_registered_only_for_worker_events() -> None:
    assert tasks.on_worker_startup in broker.event_handlers[TaskiqEvents.WORKER_STARTUP]
    assert tasks.on_worker_shutdown in broker.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]
