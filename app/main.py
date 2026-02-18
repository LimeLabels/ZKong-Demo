"""
FastAPI application entry point.
Initializes the FastAPI app, configures logging, and includes webhook routes.
"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.integrations.registry import integration_registry
from app.routers import (
    auth,
    clover_auth,
    external_webhooks,
    price_adjustments,
    products,
    shopify_auth,
    square_auth,
    store_mappings,
    webhooks,
)
from app.utils.logger import configure_logging

# Configure logging first
configure_logging()
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="Hipoink ESL Integration Middleware",
    description="Middleware for syncing Shopify and Square products to Hipoink ESL system",
    version="1.1.0",
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
app.include_router(webhooks.router)  # Consolidated webhook router (legacy + generic)
app.include_router(store_mappings.router)
app.include_router(shopify_auth.router)  # Shopify OAuth endpoints
app.include_router(shopify_auth.api_router)  # Shopify API auth endpoints
app.include_router(square_auth.router)  # Square OAuth endpoints
app.include_router(square_auth.api_router)  # Square API auth endpoints
app.include_router(clover_auth.router)  # Clover OAuth endpoints
app.include_router(price_adjustments.router)  # Time-based price adjustment schedules
app.include_router(products.router)  # Product search endpoints
app.include_router(external_webhooks.router)  # External webhooks for NCR and Square
app.include_router(auth.router)  # Authentication endpoints


@app.on_event("startup")
async def startup_event():
    """Application startup event."""
    logger.info("Hipoink ESL Integration Middleware started")

    # Log loaded integrations to verify adapters are registered
    loaded_integrations = integration_registry.list_available()
    logger.info(
        "Integration adapters loaded",
        integrations=loaded_integrations,
        count=len(loaded_integrations),
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("Hipoink ESL Integration Middleware shutting down")


@app.get("/")
async def root():
    """Root endpoint - also serves as a simple health check."""
    return {
        "status": "healthy",
        "service": "Hipoink ESL Integration Middleware",
        "version": "1.1.0",
        "integrations": integration_registry.list_available(),
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "integrations": integration_registry.list_available(),
    }


@app.get("/healthz")
async def healthz():
    """Alternative health check endpoint (Kubernetes-style)."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
