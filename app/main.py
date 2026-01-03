"""
FastAPI application entry point.
Initializes the FastAPI app, configures logging, and includes webhook routes.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.utils.logger import configure_logging
from app.routers import webhooks, store_mappings, webhooks_new, strategies, shopify_auth
import structlog

# Configure logging first
configure_logging()
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="ZKong ESL Integration Middleware",
    description="Middleware for syncing Shopify products to ZKong ESL system",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhooks.router)  # Legacy routes for backward compatibility
app.include_router(webhooks_new.router)  # New generic integration router
app.include_router(store_mappings.router)
app.include_router(strategies.router)  # Strategy management endpoints
app.include_router(shopify_auth.router)  # Shopify OAuth endpoints


@app.on_event("startup")
async def startup_event():
    """Application startup event."""
    logger.info("ZKong ESL Integration Middleware started")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("ZKong ESL Integration Middleware shutting down")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "ZKong ESL Integration Middleware",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
