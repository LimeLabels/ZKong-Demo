"""
FastAPI application entry point.
Initializes the FastAPI app, configures logging, and includes webhook routes.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.utils.logger import configure_logging
from app.routers import (
    webhooks,
    store_mappings,
    webhooks_new,
    shopify_auth,
    square_auth,
    price_adjustments,
    products,
)
from app.integrations.registry import integration_registry
# Explicitly import adapters to ensure they're loaded and registered
import app.integrations.square.adapter  # noqa: F401
import app.integrations.shopify.adapter  # noqa: F401
import structlog

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
app.include_router(webhooks.router)  # Legacy routes for backward compatibility
app.include_router(webhooks_new.router)  # New generic integration router
app.include_router(store_mappings.router)
app.include_router(shopify_auth.router)  # Shopify OAuth endpoints
app.include_router(shopify_auth.api_router)  # Shopify API auth endpoints
app.include_router(square_auth.router)  # Square OAuth endpoints
app.include_router(square_auth.api_router)  # Square API auth endpoints
app.include_router(price_adjustments.router)  # Time-based price adjustment schedules
app.include_router(products.router)  # Product search endpoints


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
    """Root endpoint."""
    return {
        "service": "Hipoink ESL Integration Middleware",
        "version": "1.1.0",
        "status": "running",
        "integrations": integration_registry.list_available(),
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
