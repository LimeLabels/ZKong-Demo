"""
Clover integration adapter.
Implements BaseIntegrationAdapter for Clover webhooks and item sync.
Webhook auth: X-Clover-Auth static comparison (no body HMAC).
Polling sync: sync_products_via_polling() for incremental + ghost-item cleanup.
"""

import secrets
import time
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from fastapi import Request, HTTPException, status
from pydantic import ValidationError
import structlog

from app.integrations.base import (
    BaseIntegrationAdapter,
    NormalizedProduct,
    NormalizedInventory,
)
from app.integrations.clover.models import CloverWebhookPayload
from app.integrations.clover.transformer import CloverTransformer
from app.integrations.clover.api_client import CloverAPIClient, CloverAPIError
from app.config import settings
from app.services.supabase_service import SupabaseService
from app.services.slack_service import get_slack_service
from app.models.database import Product, StoreMapping

logger = structlog.get_logger()


class CloverIntegrationAdapter(BaseIntegrationAdapter):
    """Clover integration adapter. Webhook verification via X-Clover-Auth (static compare)."""

    def __init__(self) -> None:
        self.transformer = CloverTransformer()
        self.supabase_service = SupabaseService()

    def get_name(self) -> str:
        return "clover"

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        headers: Dict[str, str],
    ) -> bool:
        """
        Verify webhook using X-Clover-Auth header.
        Clover does NOT sign the body; compare header value with configured auth code.
        """
        if not signature or not str(signature).strip():
            return False
        if not settings.clover_webhook_auth_code:
            logger.warning("CLOVER_WEBHOOK_AUTH_CODE not configured")
            return False
        # Router passes X-Clover-Auth as signature; constant-time compare (Clover does not HMAC body)
        return secrets.compare_digest(
            signature.strip(),
            settings.clover_webhook_auth_code.strip(),
        )

    def extract_store_id(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Optional[str]:
        """Extract first merchant ID from payload.merchants for single-store context."""
        merchants = payload.get("merchants") or {}
        if not merchants:
            return None
        first_key = next(iter(merchants), None)
        return first_key

    def transform_product(self, raw_data: Dict[str, Any]) -> List[NormalizedProduct]:
        """Transform a single Clover item to one NormalizedProduct."""
        normalized = self.transformer.transform_item(raw_data)
        return [normalized]

    def transform_inventory(
        self,
        raw_data: Dict[str, Any],
    ) -> Optional[NormalizedInventory]:
        """Phase 1: not implemented."""
        return None

    def validate_normalized_product(
        self,
        product: NormalizedProduct,
    ) -> Tuple[bool, List[str]]:
        return self.transformer.validate_normalized_product(product)

    def get_supported_events(self) -> List[str]:
        return ["inventory"]

    def _hours_since_last_cleanup(self, metadata: Dict[str, Any]) -> float:
        """Hours since clover_last_cleanup_time (ms). Returns 24+ if never run."""
        last = metadata.get("clover_last_cleanup_time") or 0
        if last <= 0:
            return 24.0
        return (time.time() * 1000 - last) / (1000 * 3600)

    async def sync_products_via_polling(
        self, store_mapping: StoreMapping
    ) -> Dict[str, Any]:
        """
        Main polling sync. Called by worker for each active Clover store mapping.
        Incremental updates via modifiedTime filter; periodic ghost-item cleanup.
        Returns: {"items_processed": int, "items_deleted": int, "errors": list}
        """
        metadata = dict(store_mapping.metadata or {})  # copy so we don't mutate the model
        access_token = metadata.get("clover_access_token")
        merchant_id = store_mapping.source_store_id
        last_sync_time = metadata.get("clover_last_sync_time", 0)
        poll_count = metadata.get("clover_poll_count", 0)
        results: Dict[str, Any] = {
            "items_processed": 0,
            "items_deleted": 0,
            "errors": [],
        }
        store_mapping_id = store_mapping.id
        if not store_mapping_id:
            results["errors"].append("Invalid store mapping (no id)")
            return results
        if not access_token:
            results["errors"].append("No access token")
            return results

        client = CloverAPIClient(access_token=access_token)
        try:
            # --- STEP A: Incremental updates (modifiedTime >= last_sync_time) ---
            items = await client.list_items_modified_since(
                merchant_id=merchant_id,
                modified_since=last_sync_time,
            )
            for item in items:
                if item.get("deleted") is True or item.get("hidden") is True:
                    await self._handle_item_deletion(item, store_mapping)
                    results["items_deleted"] += 1
                    continue
                try:
                    normalized_list = self.transform_product(item)
                    if not normalized_list:
                        continue
                    normalized = normalized_list[0]
                    is_valid, validation_errors = self.validate_normalized_product(
                        normalized
                    )
                    product = Product(
                        source_system="clover",
                        source_id=normalized.source_id,
                        source_variant_id=normalized.source_variant_id,
                        source_store_id=merchant_id,
                        title=normalized.title,
                        barcode=normalized.barcode,
                        sku=normalized.sku,
                        price=normalized.price,
                        currency=normalized.currency,
                        image_url=normalized.image_url,
                        raw_data=item,
                        normalized_data=normalized.to_dict(),
                        status="validated" if is_valid else "pending",
                        validation_errors=(
                            {"errors": validation_errors}
                            if validation_errors
                            else None
                        ),
                    )
                    saved, changed = self.supabase_service.create_or_update_product(
                        product
                    )
                    results["items_processed"] += 1
                    if is_valid and saved.id:
                        existing_hipoink = (
                            self.supabase_service.get_hipoink_product_by_product_id(
                                saved.id,
                                store_mapping_id,
                            )
                        )
                        # Queue if: new product OR product data changed (so price updates sync to ESL)
                        if changed or not existing_hipoink:
                            self.supabase_service.add_to_sync_queue(
                                product_id=saved.id,
                                store_mapping_id=store_mapping_id,
                                operation="update" if existing_hipoink else "create",
                            )
                except Exception as e:
                    logger.exception(
                        "Error processing Clover item in polling",
                        item_id=item.get("id"),
                        error=str(e),
                    )
                    results["errors"].append(
                        {"item_id": item.get("id"), "message": str(e)}
                    )

            # --- STEP B: Ghost item cleanup (every 10th poll OR every 24 hours) ---
            cleanup_interval_hours = getattr(
                settings,
                "clover_cleanup_interval_hours",
                24,
            )
            should_run_cleanup = (poll_count % 10 == 0) or (
                self._hours_since_last_cleanup(metadata) >= cleanup_interval_hours
            )
            if should_run_cleanup:
                deleted_count = await self._cleanup_ghost_items(
                    merchant_id, store_mapping, client
                )
                results["items_deleted"] += deleted_count
                metadata["clover_last_cleanup_time"] = int(time.time() * 1000)

            # --- STEP C: Update metadata ---
            metadata["clover_last_sync_time"] = int(time.time() * 1000)
            metadata["clover_poll_count"] = poll_count + 1
            self.supabase_service.update_store_mapping_metadata(
                store_mapping_id, metadata
            )
        finally:
            await client.close()

        return results

    async def _handle_item_deletion(
        self, item: Dict[str, Any], store_mapping: StoreMapping
    ) -> None:
        """Mark item as deleted in DB and queue for ESL removal (deleted/hidden in Clover)."""
        item_id = item.get("id")
        if not item_id:
            return
        await self._mark_product_deleted(str(item_id), store_mapping)

    async def _mark_product_deleted(
        self, source_id: str, store_mapping: StoreMapping
    ) -> None:
        """Mark product(s) with this source_id as deleted and queue delete for ESL."""
        store_mapping_id = store_mapping.id
        merchant_id = store_mapping.source_store_id
        if not store_mapping_id:
            return
        products_to_delete = self.supabase_service.get_products_by_source_id(
            "clover",
            source_id,
            source_store_id=merchant_id,
        )
        for product in products_to_delete:
            if product.id and product.status != "deleted":
                self.supabase_service.update_product_status(product.id, "deleted")
                self.supabase_service.add_to_sync_queue(
                    product_id=product.id,
                    store_mapping_id=store_mapping_id,
                    operation="delete",
                )

    async def _cleanup_ghost_items(
        self,
        merchant_id: str,
        store_mapping: StoreMapping,
        api_client: CloverAPIClient,
    ) -> int:
        """
        Items in our DB but not in Clover = deleted in Clover (ghost items).
        Mark them deleted and queue for ESL removal.
        """
        clover_ids = set(
            await api_client.list_all_item_ids(merchant_id=merchant_id)
        )
        our_products = self.supabase_service.get_products_by_system(
            "clover",
            source_store_id=merchant_id,
            exclude_deleted=True,
        )
        our_ids = {p.source_id for p in our_products}
        ghost_ids = our_ids - clover_ids
        for ghost_id in ghost_ids:
            await self._mark_product_deleted(ghost_id, store_mapping)
        if ghost_ids:
            logger.info(
                "Clover ghost item cleanup completed",
                merchant_id=merchant_id,
                ghost_items_found=len(ghost_ids),
            )
        return len(ghost_ids)

    async def handle_webhook(
        self,
        event_type: str,
        request: Request,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Handle Clover webhook: verification POST first, then validate payload,
        then process all merchants (collect errors, always return 200).
        """
        # a) Verification POST: dashboard sends only verificationCode
        if "verificationCode" in payload and "merchants" not in payload:
            return {"verificationCode": payload["verificationCode"]}

        # b) Payload validation
        try:
            webhook_payload = CloverWebhookPayload(**payload)
        except ValidationError as e:
            logger.error("Invalid Clover webhook payload", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload",
            ) from e

        total_updated = 0
        total_deleted = 0
        errors: List[Dict[str, str]] = []

        for merchant_id, updates in webhook_payload.merchants.items():
            try:
                store_mapping = self.supabase_service.get_store_mapping(
                    "clover",
                    merchant_id,
                )
                if not store_mapping:
                    errors.append(
                        {"merchant_id": merchant_id, "message": "No store mapping found"}
                    )
                    continue
                metadata = store_mapping.metadata or {}
                access_token = metadata.get("clover_access_token")
                if not access_token:
                    errors.append(
                        {"merchant_id": merchant_id, "message": "No access token"}
                    )
                    continue
                store_mapping_id = store_mapping.id
                if not store_mapping_id:
                    errors.append(
                        {"merchant_id": merchant_id, "message": "Invalid store mapping"}
                    )
                    continue

                client = CloverAPIClient(access_token=access_token)
                try:
                    for update in updates:
                        item_id = CloverTransformer.parse_inventory_object_id(
                            update.objectId
                        )
                        if item_id is None:
                            if CloverTransformer.INVENTORY_OBJECT_PREFIX in str(
                                update.objectId or ""
                            ):
                                logger.warning(
                                    "Malformed inventory objectId",
                                    object_id=update.objectId,
                                    merchant_id=merchant_id,
                                )
                            continue

                        if update.type == "DELETE":
                            products_to_delete = (
                                self.supabase_service.get_products_by_source_id(
                                    "clover",
                                    item_id,
                                    source_store_id=merchant_id,
                                )
                            )
                            for product in products_to_delete:
                                if product.id and store_mapping_id:
                                    self.supabase_service.add_to_sync_queue(
                                        product_id=product.id,
                                        store_mapping_id=store_mapping_id,
                                        operation="delete",
                                    )
                                    total_deleted += 1
                            continue

                        # CREATE or UPDATE: fetch item, transform, upsert, queue
                        try:
                            item_data = await client.get_item(merchant_id, item_id)
                        except CloverAPIError as api_err:
                            errors.append(
                                {
                                    "merchant_id": merchant_id,
                                    "item_id": item_id,
                                    "message": str(api_err),
                                }
                            )
                            continue
                        if not item_data:
                            continue
                        normalized_list = self.transform_product(item_data)
                        if not normalized_list:
                            continue
                        normalized = normalized_list[0]
                        is_valid, validation_errors = self.validate_normalized_product(
                            normalized
                        )
                        product = Product(
                            source_system="clover",
                            source_id=normalized.source_id,
                            source_variant_id=normalized.source_variant_id,
                            source_store_id=merchant_id,
                            title=normalized.title,
                            barcode=normalized.barcode,
                            sku=normalized.sku,
                            price=normalized.price,
                            currency=normalized.currency,
                            image_url=normalized.image_url,
                            raw_data=item_data,
                            normalized_data=normalized.to_dict(),
                            status="validated" if is_valid else "pending",
                            validation_errors=(
                                {"errors": validation_errors} if validation_errors else None
                            ),
                        )
                        saved, changed = self.supabase_service.create_or_update_product(
                            product
                        )
                        total_updated += 1
                        if is_valid and saved.id and store_mapping_id:
                            existing_hipoink = (
                                self.supabase_service.get_hipoink_product_by_product_id(
                                    saved.id,
                                    store_mapping_id,
                                )
                            )
                            if changed or not existing_hipoink:
                                self.supabase_service.add_to_sync_queue(
                                    product_id=saved.id,
                                    store_mapping_id=store_mapping_id,
                                    operation="update" if existing_hipoink else "create",
                                )
                finally:
                    await client.close()
            except Exception as e:
                logger.exception(
                    "Clover webhook processing failed for merchant",
                    merchant_id=merchant_id,
                    error=str(e),
                )
                errors.append(
                    {"merchant_id": merchant_id, "message": str(e)}
                )
                try:
                    slack = get_slack_service()
                    await slack.send_webhook_error_alert(
                        error_message=str(e),
                        integration="clover",
                        event_type=event_type,
                        merchant_id=merchant_id,
                    )
                except Exception as slack_err:
                    logger.warning("Slack alert failed", error=str(slack_err))

        return {
            "status": "ok",
            "updated": total_updated,
            "deleted": total_deleted,
            "errors": errors if errors else [],
        }

    async def sync_all_products_from_clover(
        self,
        merchant_id: str,
        access_token: str,
        store_mapping_id: UUID,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch all items from Clover and sync to DB + queue.
        Used for initial onboarding (Phase 2). Phase 1 can call with test token.
        """
        client = CloverAPIClient(access_token=access_token, base_url=base_url)
        products_created = 0
        products_updated = 0
        queued_count = 0
        errors_count = 0
        try:
            all_items = await client.list_items(merchant_id)
        except CloverAPIError as e:
            logger.error(
                "Clover sync_all_products failed",
                merchant_id=merchant_id,
                error=str(e),
            )
            return {
                "status": "error",
                "total_items": 0,
                "products_created": 0,
                "products_updated": 0,
                "queued_for_sync": 0,
                "errors": 1,
                "message": str(e),
            }
        finally:
            await client.close()

        for item in all_items:
            try:
                normalized_list = self.transform_product(item)
                if not normalized_list:
                    continue
                normalized = normalized_list[0]
                is_valid, validation_errors = self.validate_normalized_product(
                    normalized
                )
                existing = self.supabase_service.get_product_by_source(
                    source_system="clover",
                    source_id=normalized.source_id,
                    source_variant_id=normalized.source_variant_id,
                    source_store_id=merchant_id,
                )
                product = Product(
                    source_system="clover",
                    source_id=normalized.source_id,
                    source_variant_id=normalized.source_variant_id,
                    source_store_id=merchant_id,
                    title=normalized.title,
                    barcode=normalized.barcode,
                    sku=normalized.sku,
                    price=normalized.price,
                    currency=normalized.currency,
                    image_url=normalized.image_url,
                    raw_data=item,
                    normalized_data=normalized.to_dict(),
                    status="validated" if is_valid else "pending",
                    validation_errors=(
                        {"errors": validation_errors} if validation_errors else None
                    ),
                )
                saved, changed = self.supabase_service.create_or_update_product(product)
                if existing:
                    products_updated += 1
                else:
                    products_created += 1
                if is_valid and saved.id:
                    existing_hipoink = (
                        self.supabase_service.get_hipoink_product_by_product_id(
                            saved.id,
                            store_mapping_id,
                        )
                    )
                    if changed or not existing_hipoink:
                        q = self.supabase_service.add_to_sync_queue(
                            product_id=saved.id,
                            store_mapping_id=store_mapping_id,
                            operation="update" if existing_hipoink else "create",
                        )
                        if q:
                            queued_count += 1
            except Exception as e:
                logger.error(
                    "Error processing Clover item",
                    item_id=item.get("id"),
                    error=str(e),
                )
                errors_count += 1

        return {
            "status": "success",
            "total_items": len(all_items),
            "products_created": products_created,
            "products_updated": products_updated,
            "queued_for_sync": queued_count,
            "errors": errors_count,
        }
