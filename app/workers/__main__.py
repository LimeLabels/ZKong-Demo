"""
Entry point for running the sync worker as a module.
Usage: python -m app.workers
"""
import asyncio
from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker

if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_worker())

