"""
Clover BOS Diagnostic Helper for Clover time-based pricing.

Safe, read-only diagnostic that checks:
- Clover token presence and decryptability
- Clover API reachability
- Auth validity (200 vs 401/403)
- Item existence (200 vs 404)

Usage:
- Called from the price scheduler after a Clover BOS price update failure
- Optionally exposed via an external diagnostic endpoint
"""

from typing import Any, Dict, Optional

import structlog

from app.models.database import StoreMapping
from app.integrations.clover.api_client import CloverAPIClient, CloverAPIError
from app.integrations.clover.token_encryption import decrypt_tokens_from_storage

logger = structlog.get_logger()

# Fernet ciphertext prefix — if we see this as the token, decryption failed or key is missing
_FERNET_PREFIX = "gAAAAA"


async def diagnose_clover_bos(
    store_mapping: StoreMapping,
    test_item_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a read-only diagnostic against Clover to figure out why BOS
    price updates are failing for time-based pricing.

    Args:
        store_mapping: The Clover store mapping to diagnose.
        test_item_id: A known Clover item ID to probe. If None, uses
                      the first item from /v3/merchants/{mId}/items?limit=1.

    Returns:
        Dict with diagnostic results including:
          - token_status: "present" | "missing" | "encrypted_not_decrypted"
          - api_reachable: bool
          - auth_valid: bool
          - http_status: int or None
          - diagnosis: human-readable summary
    """
    results: Dict[str, Any] = {
        "store_mapping_id": str(store_mapping.id) if store_mapping.id else None,
        "merchant_id": store_mapping.source_store_id,
        "source_system": store_mapping.source_system,
        "token_status": None,
        "token_expiration": None,
        "api_reachable": False,
        "auth_valid": False,
        "http_status": None,
        "diagnosis": None,
    }

    # Step 1: Ensure this is a Clover mapping
    if store_mapping.source_system != "clover":
        results["diagnosis"] = (
            f"Store mapping is {store_mapping.source_system}, not Clover — "
            "this diagnostic only applies to Clover BOS"
        )
        logger.warning("clover_bos_diagnostic: wrong source_system", **results)
        return results

    # Step 2: Check token in metadata (after decryption)
    metadata = store_mapping.metadata or {}
    decrypted_meta = decrypt_tokens_from_storage(metadata)
    access_token = decrypted_meta.get("clover_access_token")
    raw_token = metadata.get("clover_access_token")  # before decryption
    results["token_expiration"] = decrypted_meta.get("clover_access_token_expiration")

    if not access_token:
        if isinstance(raw_token, str) and raw_token.startswith(_FERNET_PREFIX):
            results["token_status"] = "encrypted_not_decrypted"
            results["diagnosis"] = (
                "Token is present but still Fernet-encrypted — "
                "CLOVER_TOKEN_ENCRYPTION_KEY is missing or wrong in this process. "
                "The worker cannot decrypt the token, so every Clover API call fails. "
                "Fix: set the same CLOVER_TOKEN_ENCRYPTION_KEY env var in the worker."
            )
        elif raw_token is None:
            results["token_status"] = "missing"
            results["diagnosis"] = (
                "No clover_access_token in store_mapping.metadata at all. "
                "Re-run Clover OAuth or check that tokens are being saved."
            )
        else:
            results["token_status"] = "missing"
            results["diagnosis"] = (
                f"clover_access_token is falsy (value type={type(raw_token).__name__}). "
                "Token may have been cleared by decryption fallback."
            )
        logger.error("clover_bos_diagnostic: token issue", **results)
        return results

    results["token_status"] = "present"

    # Step 3: Try hitting Clover API (read-only)
    merchant_id = store_mapping.source_store_id
    if not merchant_id:
        results["diagnosis"] = "No merchant_id (source_store_id) on store mapping"
        logger.error("clover_bos_diagnostic: no merchant_id", **results)
        return results

    client = CloverAPIClient(access_token=access_token)
    try:
        # 3a: If no test_item_id provided, grab the first item from inventory
        probe_item_id = test_item_id
        if not probe_item_id:
            try:
                http_client = await client._get_client()
                url = f"{client.base_url}/v3/merchants/{merchant_id}/items"
                resp = await http_client.get(
                    url,
                    headers=client._headers(),
                    params={"limit": 1},
                    timeout=10.0,
                )
                results["list_items_status"] = resp.status_code

                if resp.status_code == 401:
                    results["auth_valid"] = False
                    results["api_reachable"] = True
                    results["http_status"] = 401
                    results["diagnosis"] = (
                        "Clover returned 401 on list items — token is invalid or expired. "
                        "Check clover_access_token_expiration and trigger a token refresh."
                    )
                    logger.error("clover_bos_diagnostic: 401 on list", **results)
                    return results

                if resp.status_code == 403:
                    results["auth_valid"] = False
                    results["api_reachable"] = True
                    results["http_status"] = 403
                    results["diagnosis"] = (
                        "Clover returned 403 — token lacks permissions. "
                        "Check app permissions in Clover dashboard (needs INVENTORY_R, INVENTORY_W)."
                    )
                    logger.error("clover_bos_diagnostic: 403 on list", **results)
                    return results

                if resp.status_code != 200:
                    results["api_reachable"] = True
                    results["http_status"] = resp.status_code
                    results["diagnosis"] = (
                        f"Unexpected {resp.status_code} from Clover list items. "
                        f"Body: {resp.text[:300]}"
                    )
                    logger.error("clover_bos_diagnostic: unexpected status on list", **results)
                    return results

                # 200 — grab first item ID
                data = resp.json()
                elements = data.get("elements", [])
                if elements:
                    probe_item_id = elements[0].get("id")
                else:
                    results["api_reachable"] = True
                    results["auth_valid"] = True
                    results["http_status"] = 200
                    results["diagnosis"] = (
                        "Clover API reachable and auth valid, but merchant has ZERO items. "
                        "Time-based pricing has nothing to update."
                    )
                    logger.warning("clover_bos_diagnostic: no items", **results)
                    return results

            except Exception as e:
                if "ConnectError" in type(e).__name__ or "ConnectTimeout" in type(e).__name__:
                    results["diagnosis"] = (
                        f"Cannot reach Clover API — network/DNS issue. Error: {e}"
                    )
                else:
                    results["diagnosis"] = f"Error listing items: {type(e).__name__}: {e}"
                logger.error("clover_bos_diagnostic: list items failed", error=str(e), **results)
                return results

        # 3b: GET a single item (read-only probe)
        results["api_reachable"] = True

        try:
            item = await client.get_item(merchant_id, probe_item_id)
            if item:
                results["auth_valid"] = True
                results["http_status"] = 200
                results["probe_item_id"] = probe_item_id
                results["probe_item_name"] = item.get("name")
                results["probe_item_price_cents"] = item.get("price")
                results["diagnosis"] = (
                    "ALL CLEAR — Clover API reachable, auth valid, item readable. "
                    "If BOS prices are still not updating, check: "
                    "(1) schedule is_active=True and next_trigger_at is in the past, "
                    "(2) product 'pc' field in schedule matches actual Clover item IDs, "
                    "(3) 'pp' price values are > 0, "
                    "(4) worker is actually running (price_scheduler checks every 60s)."
                )
            else:
                results["http_status"] = 404
                results["probe_item_id"] = probe_item_id
                results["diagnosis"] = (
                    f"Item {probe_item_id} not found (404). Auth and connectivity are fine. "
                    "Check that schedule product codes match real Clover item IDs."
                )

        except CloverAPIError as e:
            results["http_status"] = e.status_code
            results["probe_item_id"] = probe_item_id
            if e.status_code in (401, 403):
                results["auth_valid"] = False
            results["diagnosis"] = (
                f"Clover API error on get_item: {e.status_code} — {e.message}. "
                f"Body: {(e.body or '')[:300]}"
            )
            logger.error("clover_bos_diagnostic: get_item failed", **results)

    except Exception as e:
        results["diagnosis"] = f"Unexpected error during diagnostic: {type(e).__name__}: {e}"
        logger.error("clover_bos_diagnostic: unexpected error", error=str(e), **results)
    finally:
        try:
            await client.close()
        except Exception:
            pass

    logger.info("clover_bos_diagnostic: complete", **results)
    return results

