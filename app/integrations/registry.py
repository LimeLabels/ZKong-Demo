"""
Integration registry for auto-discovery and management of integrations.
"""

import structlog

from app.integrations.base import BaseIntegrationAdapter

logger = structlog.get_logger()


class IntegrationRegistry:
    """Registry that manages and provides access to all integrations."""

    def __init__(self):
        """Initialize the integration registry."""
        self._integrations: dict[str, BaseIntegrationAdapter] = {}
        self._load_integrations()

    def _load_integrations(self):
        """Load all available integrations."""
        # Try to load Shopify integration
        try:
            from app.integrations.shopify.adapter import ShopifyIntegrationAdapter

            shopify_adapter = ShopifyIntegrationAdapter()
            self.register(shopify_adapter)
            logger.info("Loaded Shopify integration", adapter_name=shopify_adapter.get_name())
        except ImportError as e:
            logger.warning("Could not load Shopify integration", error=str(e))
        except Exception as e:
            logger.error("Error loading Shopify integration", error=str(e))

        # Try to load NCR integration
        try:
            from app.integrations.ncr.adapter import NCRIntegrationAdapter

            ncr_adapter = NCRIntegrationAdapter()
            self.register(ncr_adapter)
            logger.info("Loaded NCR integration", adapter_name=ncr_adapter.get_name())
        except ImportError as e:
            logger.warning("Could not load NCR integration", error=str(e))
        except Exception as e:
            logger.error("Error loading NCR integration", error=str(e))

        # Future integrations will be loaded here
        # Try to load Square integration
        try:
            from app.integrations.square.adapter import SquareIntegrationAdapter

            square_adapter = SquareIntegrationAdapter()
            self.register(square_adapter)
            logger.info("Loaded Square integration", adapter_name=square_adapter.get_name())
        except ImportError as e:
            logger.warning("Could not load Square integration", error=str(e))
        except Exception as e:
            logger.error("Error loading Square integration", error=str(e))

        # Try to load Clover integration
        try:
            from app.integrations.clover.adapter import CloverIntegrationAdapter

            clover_adapter = CloverIntegrationAdapter()
            self.register(clover_adapter)
            logger.info("Loaded Clover integration", adapter_name=clover_adapter.get_name())
        except ImportError as e:
            logger.warning("Could not load Clover integration", error=str(e))
        except Exception as e:
            logger.error("Error loading Clover integration", error=str(e))

    def register(self, adapter: BaseIntegrationAdapter):
        """
        Register an integration adapter.

        Args:
            adapter: Integration adapter instance
        """
        name = adapter.get_name()
        if name in self._integrations:
            logger.warning("Integration already registered, replacing", integration_name=name)
        self._integrations[name] = adapter
        logger.info("Registered integration", integration_name=name)

    def get_adapter(self, integration_name: str) -> BaseIntegrationAdapter | None:
        """
        Get adapter for specific integration.

        Args:
            integration_name: Name of the integration (e.g., 'shopify')

        Returns:
            Integration adapter instance, or None if not found
        """
        return self._integrations.get(integration_name.lower())

    def list_available(self) -> list[str]:
        """
        List all available integrations.

        Returns:
            List of integration names
        """
        return list(self._integrations.keys())

    def is_available(self, integration_name: str) -> bool:
        """
        Check if an integration is available.

        Args:
            integration_name: Name of the integration

        Returns:
            True if available, False otherwise
        """
        return integration_name.lower() in self._integrations


# Global registry instance
integration_registry = IntegrationRegistry()
