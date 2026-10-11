from __future__ import annotations

import asyncio
import logging
import time
from datetime import timezone

from sqlalchemy import select

from app.db.models import ImportTask, ImportTaskStatus
from app.db.base import utc_now
from app.db.session import AsyncSessionFactory
from app.services.recognition_tasks import (
    cleanup_expired_images,
    process_order_task,
)
from app.services.reminders import dispatch_due_reminders


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recognition-worker")


async def run_worker() -> None:
    logger.info("recognition worker started")
    last_reminder_check = 0.0
    while True:
        try:
            async with AsyncSessionFactory() as session:
                if time.monotonic() - last_reminder_check >= 30:
                    delivered = await dispatch_due_reminders(session)
                    if delivered:
                        logger.info(
                            "sent %s scheduled reminder deliveries",
                            delivered,
                        )
                    last_reminder_check = time.monotonic()
                await cleanup_expired_images(session)
                task = await session.scalar(
                    select(ImportTask)
                    .where(
                        ImportTask.source == "order_images",
                        ImportTask.status == ImportTaskStatus.PROCESSING,
                    )
                    .order_by(ImportTask.created_at)
                    .limit(1)
                )
                if task is not None:
                    queued_at = task.updated_at
                    if queued_at.tzinfo is None:
                        queued_at = queued_at.replace(tzinfo=timezone.utc)
                    queue_wait_ms = max(
                        0,
                        (utc_now() - queued_at).total_seconds() * 1000,
                    )
                    logger.info(
                        "processing recognition task %s queue_wait_ms=%.1f",
                        task.id,
                        queue_wait_ms,
                    )
                    await process_order_task(session, task)
                    continue
        except Exception:
            logger.exception("recognition worker iteration failed")
        await asyncio.sleep(2)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
