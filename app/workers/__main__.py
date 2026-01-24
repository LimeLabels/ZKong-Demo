"""
Entry point for running workers as a module.
Runs sync worker, price scheduler, and token refresh scheduler concurrently.
Usage: python -m app.workers
"""

import asyncio
from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker
from app.workers.price_scheduler import run_price_scheduler
from app.workers.token_refresh_scheduler import run_token_refresh_scheduler


async def run_all_workers():
    """Run all workers concurrently."""
    await asyncio.gather(
        run_worker(),
        run_price_scheduler(),
        run_token_refresh_scheduler(),
    )


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_all_workers())
