"""
Entry point for running workers as a module.
Runs sync worker, price scheduler, token refresh scheduler, and NCR sync worker concurrently.
Usage: python -m app.workers
"""

import asyncio
from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker
from app.workers.price_scheduler import run_price_scheduler
from app.workers.token_refresh_scheduler import run_token_refresh_scheduler
# from app.workers.ncr_sync_worker import run_ncr_sync_worker  # Temporarily disabled


async def run_all_workers():
    """Run all workers concurrently."""
    await asyncio.gather(
        run_worker(),  # ESL sync worker
        run_price_scheduler(),  # Price schedule worker
        run_token_refresh_scheduler(),  # Token refresh scheduler
        # run_ncr_sync_worker(),  # NCR product discovery worker - temporarily disabled
    )


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_all_workers())
