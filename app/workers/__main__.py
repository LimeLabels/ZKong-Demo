"""
Entry point for running workers as a module.
Runs sync worker, price scheduler, token refresh scheduler, and Clover sync worker concurrently.
Usage: python -m app.workers

Starts a minimal HTTP server on PORT (if set) for /health so platforms like Railway
can health-check the worker and not remove the deployment.
"""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.utils.logger import configure_logging
from app.workers.sync_worker import run_worker
from app.workers.price_scheduler import run_price_scheduler
from app.workers.token_refresh_scheduler import run_token_refresh_scheduler
from app.workers.clover_sync_worker import run_clover_sync_worker
# from app.workers.ncr_sync_worker import run_ncr_sync_worker  # Temporarily disabled


def _run_health_server():
    """Run a minimal HTTP server for GET /health so Railway health checks pass."""
    port = int(os.environ.get("PORT", 8080))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health" or self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):  # noqa: D401 - suppress request logs
            pass

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


async def run_all_workers():
    """Run all workers concurrently."""
    await asyncio.gather(
        run_worker(),  # ESL sync worker
        run_price_scheduler(),  # Price schedule worker
        run_token_refresh_scheduler(),  # Token refresh scheduler
        run_clover_sync_worker(),  # Clover polling sync
        # run_ncr_sync_worker(),  # NCR product discovery worker - temporarily disabled
    )


if __name__ == "__main__":
    configure_logging()
    # Start health server so Railway (and similar) health checks pass; worker has no HTTP otherwise
    if os.environ.get("PORT"):
        daemon = threading.Thread(target=_run_health_server, daemon=True)
        daemon.start()
    asyncio.run(run_all_workers())
