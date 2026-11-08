"""Enqueue the infrastructure probe from a running application environment."""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from virtual_company.task_queue.broker import broker
from virtual_company.task_queue.tasks import infrastructure_probe


async def enqueue(identifier: str, sleep_seconds: float) -> None:
    """Connect to the broker and enqueue one probe without awaiting its result."""
    await broker.startup()
    try:
        task = await infrastructure_probe.kiq(identifier, sleep_seconds)
        print(f"Enqueued probe {identifier} as Taskiq task {task.task_id}")
    finally:
        await broker.shutdown()


def main() -> None:
    """Parse the small probe-only command line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identifier", default=str(uuid4()))
    parser.add_argument("--sleep-seconds", type=float, default=0)
    args = parser.parse_args()
    asyncio.run(enqueue(args.identifier, args.sleep_seconds))


if __name__ == "__main__":
    main()
