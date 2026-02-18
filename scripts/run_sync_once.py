"""
Single-pass sync worker for GitHub Actions.
Drains pending items from sync_queue, processes them, then exits.
Designed to run on a cron schedule (every 3 minutes).

Reuses SyncWorker.process_sync_queue() — no duplication of sync logic.
"""

import asyncio
import sys

import structlog

from app.utils.logger import configure_logging
from app.workers.sync_worker import SyncWorker

configure_logging()
logger = structlog.get_logger()

MAX_BATCHES = 20
BATCH_SIZE = 10


async def main() -> None:
    worker = SyncWorker()
    total_processed = 0
    batch_count = 0

    try:
        logger.info("GitHub Actions sync worker: starting queue drain")

        while batch_count < MAX_BATCHES:
            items = worker.supabase_service.get_pending_sync_queue_items(limit=BATCH_SIZE)

            if not items:
                logger.info(
                    "No more pending items in queue",
                    total_processed=total_processed,
                    batches_run=batch_count,
                )
                break

            logger.info(
                "Processing batch",
                batch_number=batch_count + 1,
                items_in_batch=len(items),
            )

            await worker.process_sync_queue()
            total_processed += len(items)
            batch_count += 1

        if batch_count >= MAX_BATCHES:
            logger.warning(
                "Hit max batch limit — queue may still have items",
                max_batches=MAX_BATCHES,
                total_processed=total_processed,
            )

        logger.info(
            "GitHub Actions sync worker: done",
            total_processed=total_processed,
            batches_run=batch_count,
        )

    except Exception as e:
        logger.error("Sync worker failed", error=str(e), total_processed=total_processed)
        sys.exit(1)

    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
