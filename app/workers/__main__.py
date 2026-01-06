"""
Entry point for running workers as a module.
Runs both sync worker and price scheduler concurrently.
Usage: python -m app.workers
"""

import asyncio
from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker
from app.workers.price_scheduler import run_price_scheduler

async def run_all_workers():
    """Run both sync worker and price scheduler concurrently."""
    await asyncio.gather(
        run_worker(),
        run_price_scheduler(),
    )

if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_all_workers())
