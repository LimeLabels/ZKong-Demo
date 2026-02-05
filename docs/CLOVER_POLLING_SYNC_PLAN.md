# Clover Polling-Based Inventory Sync Plan

## Executive Summary

Since Clover webhooks are unreliable in sandbox (and potentially production), this plan implements a **polling-based sync worker** that periodically queries Clover's REST API for inventory changes using the `modifiedTime` filter. This mirrors your existing Square `sync_all_products` pattern but runs continuously as a background worker, similar to your `sync_worker` and `price_scheduler`.

**Status:** ✅ **Feasible and Production-Ready**  
**Pattern:** Matches Square/NCR/Shopify integration architecture  
**Risk:** Low (uses existing worker infrastructure)

---

## Approved Revisions (Incorporated)

The following revisions from code review are **approved** and reflected in this plan:

| Revision | Description |
|----------|-------------|
| **Adapter-centric** | Main polling logic lives in **adapter** as `sync_products_via_polling(store_mapping)`. Worker is a thin wrapper that iterates merchants and calls the adapter. |
| **Ghost item cleanup** | Periodically compare Clover item IDs vs our DB. Items in DB but not in Clover = deleted (ghost items). Run every 10th poll OR every 24 hours. |
| **list_all_item_ids()** | Lightweight API method to fetch only item IDs (`fields=id`) for ghost cleanup, avoiding full item payloads. |
| **Filter syntax** | Use URL query param: `GET /v3/merchants/{mId}/items?filter=modifiedTime>={timestamp}&limit=100` (not dict param). |
| **Cents → dollars** | Transformer must convert Clover `price` (cents) and optional `cost` (cents) to dollars. Gas-station context: fuel/tobacco/drinks. |
| **Transformer extra_data** | Optional: `unit_cost`, `price_type`, `modified_time` in `extra_data` for gas-station / variable pricing. |
| **Deleted / hidden items** | In polling response, if `item.deleted == True` or `item.hidden == True`: treat as delete (mark in DB, queue for ESL removal). Tobacco/age-restricted may be `hidden` — still sync deletion. |
| **get_supported_events** | **Keep** `["inventory"]` for webhook route compatibility (`/webhooks/clover/inventory`). Do **not** change to `items.created` etc. |
| **Config** | Add `clover_cleanup_interval_hours: int = 24`. |
| **Supabase** | Require `update_store_mapping_metadata(mapping_id, metadata_dict)` to merge and persist `clover_last_sync_time`, `clover_poll_count`, `clover_last_cleanup_time`. If missing, implement or use get + merge + update. |
| **Gas station** | Document: high SKU counts (500–2000), frequent price changes (fuel), variable pricing, tobacco/alcohol (hidden). |
| **Testing checklist** | Post-implementation checklist added (create/update/delete/hide item, multi-merchant). |

---

## Problem Statement

**Current Issue:**
- Clover webhooks configured correctly (`X-Clover-Auth` verified, URL correct, Inventory subscribed)
- Postman requests to `/webhooks/clover/inventory` return `200 OK` ✅
- **But:** Clover never sends webhooks when items are created/edited in merchant dashboard ❌
- This is a **Clover-side issue** (not our code)

**Solution:**
- Implement a **polling worker** that queries Clover REST API every N minutes
- Use `modifiedTime` filter to fetch only changed items since last poll
- Store `last_sync_time` per merchant in `store_mapping.metadata`
- Transform and queue changes → same flow as webhooks (DB → Queue → Hipoink)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Clover Polling Sync Worker (runs every 5-15 minutes)      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │  For each active Clover store mapping: │
        │  1. Get last_sync_time from metadata  │
        │  2. Query Clover API:                 │
        │     GET /items?filter=modifiedTime>=X  │
        │  3. Transform items → Normalized     │
        │  4. Upsert to products table           │
        │  5. Add to sync_queue                  │
        │  6. Update last_sync_time              │
        └───────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │  Existing Sync Worker (every 5 sec)   │
        │  Processes sync_queue → Hipoink        │
        └───────────────────────────────────────┘
```

**Key Points:**
- **Non-breaking:** Webhook endpoint stays active (if Clover fixes webhooks later, both work)
- **Efficient:** Only fetches changed items using `modifiedTime` filter
- **Consistent:** Uses same transform → DB → queue → Hipoink flow as Square/Shopify
- **Multi-tenant:** Each merchant has independent `last_sync_time`

---

## Implementation Plan

### Phase 1: Extend API Client (`app/integrations/clover/api_client.py`)

**1. Add method to fetch items modified since a timestamp:**

```python
async def list_items_modified_since(
    self,
    merchant_id: str,
    modified_since: int,  # Unix timestamp in MILLISECONDS
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Fetch items modified since timestamp.
    
    IMPORTANT: Use URL query param format, NOT dict param.
    GET /v3/merchants/{mId}/items?filter=modifiedTime>={timestamp}&limit=100&offset=0
    
    Handle pagination with offset. Access token from store_mapping.metadata.get("clover_access_token").
    """
```

**2. Add lightweight method for ghost-item cleanup:**

```python
async def list_all_item_ids(self, merchant_id: str) -> List[str]:
    """
    Fetch ONLY item IDs (fast query for deletion detection).
    
    GET /v3/merchants/{mId}/items?fields=id
    (Or equivalent minimal fields — check Clover docs for sparse fields.)
    
    Used for ghost item cleanup: compare with our DB to find items deleted in Clover.
    """
```

**Why:** Clover REST API supports `filter=modifiedTime>=[unix-ms]` (Apply filters to API requests). Sparse field selection reduces payload when only IDs are needed.

---

### Phase 2: Adapter Method + Thin Worker

**2a. Adapter: add `sync_products_via_polling(store_mapping)` (`app/integrations/clover/adapter.py`)**

The **main polling logic** lives in the adapter (same pattern as Square’s `sync_all_products_from_square`). The adapter must implement:

```python
async def sync_products_via_polling(self, store_mapping: StoreMapping) -> Dict[str, Any]:
    """
    Main polling sync. Called by worker for each active Clover store mapping.
    
    Returns: {"items_processed": int, "items_deleted": int, "errors": list}
    """
    metadata = store_mapping.metadata or {}
    access_token = metadata.get("clover_access_token")
    merchant_id = store_mapping.source_store_id
    last_sync_time = metadata.get("clover_last_sync_time", 0)
    poll_count = metadata.get("clover_poll_count", 0)
    results = {"items_processed": 0, "items_deleted": 0, "errors": []}

    # --- STEP A: Incremental updates (modifiedTime >= last_sync_time) ---
    items = await api_client.list_items_modified_since(merchant_id, modified_since=last_sync_time)
    for item in items:
        if item.get("deleted") == True or item.get("hidden") == True:
            await self._handle_item_deletion(item, store_mapping)
            results["items_deleted"] += 1
            continue
        # Transform, upsert, add to sync_queue (same as webhook handler)
        results["items_processed"] += 1

    # --- STEP B: Ghost item cleanup (every 10th poll OR every 24 hours) ---
    should_cleanup = (poll_count % 10 == 0) or (hours_since(metadata.get("clover_last_cleanup_time")) >= 24)
    if should_cleanup:
        deleted_count = await self._cleanup_ghost_items(merchant_id, store_mapping)
        results["items_deleted"] += deleted_count
        metadata["clover_last_cleanup_time"] = int(time.time() * 1000)

    # --- STEP C: Update metadata ---
    metadata["clover_last_sync_time"] = int(time.time() * 1000)
    metadata["clover_poll_count"] = poll_count + 1
    supabase_service.update_store_mapping_metadata(store_mapping.id, metadata)

    return results
```

**Ghost cleanup (adapter):**

```python
async def _cleanup_ghost_items(self, merchant_id: str, store_mapping: StoreMapping) -> int:
    """Items in our DB but not in Clover = deleted in Clover (ghost items)."""
    clover_ids = set(await self.api_client.list_all_item_ids(merchant_id))
    our_products = self.supabase_service.get_products_by_system(
        "clover", source_store_id=merchant_id, exclude_deleted=True
    )
    our_ids = {p.source_id for p in our_products}
    ghost_ids = our_ids - clover_ids
    for gid in ghost_ids:
        await self._mark_product_deleted(gid, store_mapping)  # status=deleted, add to sync_queue delete
    return len(ghost_ids)
```

**2b. Worker: thin wrapper (`app/workers/clover_sync_worker.py`)**

Worker only iterates mappings and calls the adapter:

```python
class CloverSyncWorker:
    """Polls Clover via adapter. Runs every N minutes (default 5)."""
    def __init__(self):
        self.adapter = CloverIntegrationAdapter()  # from registry or direct import
        self.supabase_service = SupabaseService()

    async def poll_all_merchants(self):
        mappings = self.supabase_service.get_store_mappings_by_source_system("clover")
        for mapping in mappings:
            if not mapping.is_active or not (mapping.metadata or {}).get("clover_access_token"):
                continue
            try:
                results = await self.adapter.sync_products_via_polling(mapping)
                logger.info("Clover sync completed", merchant_id=mapping.source_store_id, **results)
            except Exception as e:
                logger.error("Failed to sync Clover merchant", merchant_id=mapping.source_store_id, error=str(e))
```

---

### Phase 3: Add Config & Register Worker

**Add to `app/config.py`:**

```python
# Clover Polling Configuration
clover_sync_interval_seconds: int = 300   # Poll every 5 minutes (default)
clover_sync_enabled: bool = True          # Toggle polling on/off
clover_cleanup_interval_hours: int = 24   # Full ghost-item cleanup every 24 hours
```

**Add to `app/workers/__main__.py`:**

```python
from app.workers.clover_sync_worker import run_clover_sync_worker

async def run_all_workers():
    await asyncio.gather(
        run_worker(),  # ESL sync worker
        run_price_scheduler(),
        run_token_refresh_scheduler(),
        run_clover_sync_worker(),  # NEW: Clover polling worker
    )
```

---

### Phase 4: Handle Edge Cases

**1. First Run (no last_sync_time):**
- Use `last_sync_time = 0` → fetches all items (like `sync_all_products_from_clover`)
- After first sync, store current timestamp

**2. Deleted / hidden items:**
- In polling response: if `item.deleted == True` or `item.hidden == True` → treat as delete (mark in DB, queue for ESL removal).
- Clover API does not return deleted items in `modifiedTime` filtered queries.
- **Ghost cleanup:** Periodically fetch all item IDs from Clover; compare with our DB; items in DB but not in Clover = ghost items → mark deleted and queue delete. Run every 10th poll or every 24 hours.

**3. Rate Limiting:**
- Clover may have rate limits (not documented, but assume ~100 req/min)
- **Solution:** Add delay between merchants if polling multiple stores
- Use existing `PAGINATION_DELAY_SECONDS` pattern

**4. Token Refresh:**
- OAuth tokens expire (Phase 2 concern)
- For Phase 1 (test tokens): tokens don't expire, but handle 401 gracefully
- Log and skip merchant if token invalid (don't crash worker)

**5. Concurrent Polling:**
- If webhooks start working later, both systems might process same item
- **Solution:** `create_or_update_product` is idempotent (uses `source_id` + `source_variant_id` as unique key)
- `add_to_sync_queue` has deduplication logic already

---

## Database Schema Changes

**No schema changes needed!** ✅

- `store_mapping.metadata` (JSONB) stores `clover_last_sync_time`
- `products` table already supports Clover (`source_system="clover"`)
- `sync_queue` already handles Clover products

**Metadata structure:**

```json
{
  "clover_access_token": "5e2ad16e-1fe8-c8c0-3728-0fef56b445da",
  "clover_last_sync_time": 1707123456789,
  "clover_poll_count": 42,
  "clover_last_cleanup_time": 1707123456789
}
```

**Supabase:** Implement or use `update_store_mapping_metadata(mapping_id, metadata_dict)` that **merges** the given dict into existing `metadata` and persists (get mapping → merge → update). If not present, add to `SupabaseService`.

---

## File Structure

```
app/
├── integrations/
│   └── clover/
│       ├── api_client.py          # ADD: list_items_modified_since(), list_all_item_ids()
│       ├── adapter.py             # ADD: sync_products_via_polling(), _cleanup_ghost_items(), _handle_item_deletion(), _mark_product_deleted()
│       ├── transformer.py         # Optional: extra_data (unit_cost, price_type, modified_time); ensure cents→dollars
│       └── models.py               # No change required
└── workers/
    ├── clover_sync_worker.py      # NEW: Thin wrapper — calls adapter.sync_products_via_polling()
    └── __main__.py                 # ADD: run_clover_sync_worker()
```

**Webhook:** Keep `get_supported_events()` as `["inventory"]` so `/webhooks/clover/inventory` remains valid. Do not change to `items.created` etc.

---

## Testing Strategy

### 1. Unit Tests

- Test `list_items_modified_since()` with mock API responses
- Test `poll_merchant()` with sample items
- Test `last_sync_time` update logic

### 2. Integration Tests

- Create test store mapping with `clover_last_sync_time` in metadata
- Mock Clover API to return items with `modifiedTime` > last_sync_time
- Verify items are transformed, upserted, and queued correctly

### 3. Manual Testing

**Step 1: Initial Sync (first run)**
```bash
# Set last_sync_time = 0 in metadata (or don't set it)
# Run worker → should fetch ALL items
# Verify all items in products table
# Verify last_sync_time updated to current time
```

**Step 2: Incremental Sync**
```bash
# Edit an item in Clover dashboard
# Wait for polling interval (5 minutes)
# Verify only that item is fetched (not all items)
# Verify item updated in DB and queued
```

**Step 3: Multi-Merchant**
```bash
# Create 2 store mappings (different merchants)
# Edit items in both merchants
# Run worker → should poll both merchants independently
# Verify each merchant's last_sync_time updated separately
```

---

## Performance Considerations

### Polling Interval

**Recommended:** 5-15 minutes

- **Too frequent (1 min):** Unnecessary API calls, risk rate limiting
- **Too infrequent (1 hour):** Delayed updates, poor UX
- **Sweet spot:** 5-15 minutes balances freshness vs. API load

**Configurable per merchant (future):**
- Store `clover_sync_interval` in metadata
- High-volume merchants: 5 min
- Low-volume merchants: 15 min

### API Efficiency

**Current approach (webhook):**
- Clover sends webhook → instant (0 API calls from us)

**Polling approach:**
- 1 API call per merchant per poll interval
- Example: 10 merchants × 1 call/5min = 2 calls/min = 120 calls/hour
- **Well within Clover's rate limits** (assumed ~100 req/min)

**Optimization:** Only poll merchants with `is_active=True` and valid `clover_access_token`

---

## Comparison: Webhooks vs Polling

| Aspect | Webhooks (Ideal) | Polling (Fallback) |
|--------|------------------|-------------------|
| **Latency** | Instant (< 1 sec) | 5-15 min delay |
| **API Calls** | 0 (Clover pushes) | 1 per merchant per interval |
| **Reliability** | Depends on Clover | 100% reliable (we control it) |
| **Complexity** | Simple (receive POST) | Moderate (poll loop + state) |
| **Cost** | Free (Clover's bandwidth) | Minimal (our API calls) |

**Verdict:** Polling is a **perfectly acceptable fallback** for Clover. Many integrations use polling (e.g., NCR, some Square use cases). The 5-15 min delay is acceptable for inventory sync.

---

## Migration Path

### Phase 1: Implement Polling (Current)

1. ✅ Add `list_items_modified_since()` to `api_client.py`
2. ✅ Create `clover_sync_worker.py`
3. ✅ Register worker in `__main__.py`
4. ✅ Add config settings
5. ✅ Deploy and test

**Webhook endpoint stays active** (if Clover fixes webhooks, both work simultaneously)

### Phase 2: Optimize (Future)

- **Hybrid approach:** Use webhooks when available, fallback to polling
- **Smart polling:** Increase interval if webhooks are working
- **Per-merchant intervals:** High-volume merchants poll more frequently

### Phase 3: OAuth Integration (Later)

- Replace test tokens with OAuth access tokens
- Add token refresh logic (similar to Square)
- Polling worker handles token refresh automatically

---

## Code Examples

### Example 1: API Client Method

```python
async def list_items_modified_since(
    self,
    merchant_id: str,
    modified_since: int,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Fetch items modified since timestamp."""
    all_items: List[Dict[str, Any]] = []
    offset = 0
    client = await self._get_client()
    
    while True:
        url = f"{self.base_url}/v3/merchants/{merchant_id}/items"
        params = {
            "limit": limit,
            "offset": offset,
            "filter": f"modifiedTime>={modified_since}",  # Clover filter syntax
        }
        
        response = await client.get(url, headers=self._headers(), params=params)
        # ... handle response, pagination, etc.
        
        items = response.json().get("elements", [])
        all_items.extend(items)
        
        if len(items) < limit:
            break
        offset += limit
        await asyncio.sleep(PAGINATION_DELAY_SECONDS)
    
    return all_items
```

### Example 2: Worker Poll Logic

```python
async def poll_merchant(self, store_mapping: StoreMapping):
    """Poll single merchant for changes."""
    metadata = store_mapping.metadata or {}
    access_token = metadata.get("clover_access_token")
    merchant_id = store_mapping.source_store_id
    
    if not access_token:
        logger.warning("No access token for merchant", merchant_id=merchant_id)
        return
    
    # Get last sync time (default to 0 for first run)
    last_sync_time = metadata.get("clover_last_sync_time", 0)
    
    try:
        client = CloverAPIClient(access_token=access_token)
        items = await client.list_items_modified_since(
            merchant_id=merchant_id,
            modified_since=last_sync_time,
        )
        
        updated_count = 0
        for item in items:
            # Transform → Upsert → Queue (same as webhook handler)
            normalized_list = self.transformer.transform_item(item)
            # ... existing logic from adapter.handle_webhook()
            updated_count += 1
        
        # Update last_sync_time
        current_time_ms = int(time.time() * 1000)
        self.supabase_service.update_store_mapping_metadata(
            store_mapping.id,
            {"clover_last_sync_time": current_time_ms}
        )
        
        logger.info(
            "Clover sync completed",
            merchant_id=merchant_id,
            items_fetched=len(items),
            items_updated=updated_count,
        )
    except CloverAPIError as e:
        logger.error("Clover API error during poll", merchant_id=merchant_id, error=str(e))
    finally:
        await client.close()
```

---

## Configuration

**Add to `.env`:**

```env
# Clover Polling (fallback when webhooks don't work)
CLOVER_SYNC_INTERVAL_SECONDS=300  # Poll every 5 minutes
CLOVER_SYNC_ENABLED=true  # Set false to disable polling
```

**Add to `app/config.py`:**

```python
# Clover Polling Configuration
clover_sync_interval_seconds: int = 300  # 5 minutes default
clover_sync_enabled: bool = True
```

---

## Monitoring & Alerts

**Logs to watch:**

1. **Successful polls:**
   ```
   [info] Clover sync completed merchant_id=ZMG2QE2VNW0E1 items_fetched=5 items_updated=5
   ```

2. **No changes:**
   ```
   [info] Clover sync completed merchant_id=ZMG2QE2VNW0E1 items_fetched=0 items_updated=0
   ```

3. **Errors:**
   ```
   [error] Clover API error during poll merchant_id=ZMG2QE2VNW0E1 error=401 Unauthorized
   ```

**Slack alerts:** Use existing `slack_service` to alert on:
- Repeated API errors (401, 429 rate limit)
- Worker crashes
- No items fetched for > 1 hour (possible API issue)

---

## Rollout Plan

### Step 1: Implement & Test Locally (1-2 hours)

1. Add `list_items_modified_since()` to `api_client.py`
2. Create `clover_sync_worker.py` (copy pattern from `sync_worker.py`)
3. Add config settings
4. Register worker in `__main__.py`
5. Test locally with test merchant

### Step 2: Deploy to Railway (30 min)

1. Push code to GitHub
2. Railway auto-deploys
3. Verify worker starts (check logs: "Clover sync worker started")
4. Wait 5 minutes → verify first poll runs
5. Edit item in Clover → wait 5 min → verify sync

### Step 3: Monitor & Adjust (Ongoing)

1. Watch logs for first 24 hours
2. Adjust `CLOVER_SYNC_INTERVAL_SECONDS` if needed
3. Verify items syncing to Hipoink correctly

---

## Success Criteria

✅ **Worker runs continuously** (no crashes)  
✅ **Polls every N minutes** (configurable)  
✅ **Fetches only changed items** (using `modifiedTime` filter)  
✅ **Items sync to DB → Queue → Hipoink** (same flow as webhooks)  
✅ **Multi-tenant safe** (each merchant has independent `last_sync_time`)  
✅ **Non-breaking** (webhook endpoint still works if Clover fixes it)

---

## References

- [Clover REST API - Apply filters](https://docs.clover.com/dev/docs/applying-filters)
- [Clover REST API - Get all inventory items](https://docs.clover.com/dev/reference/inventorygetitems)
- [Clover Inventory FAQs](https://docs.clover.com/dev/docs/inventory-faqs)
- Your existing `app/workers/sync_worker.py` (pattern to follow)
- Your existing `app/integrations/square/adapter.py` → `sync_all_products_from_clover()` (similar logic)

---

## Conclusion

This polling-based approach is **production-ready, efficient, and follows your existing patterns**. It solves the Clover webhook reliability issue while maintaining the same data flow (Clover → DB → Queue → Hipoink) as Square/Shopify.

**Estimated implementation time:** 2-3 hours  
**Risk level:** Low (uses existing infrastructure)  
**Maintenance:** Minimal (runs automatically, logs errors)

**Ready to implement?** ✅ Yes - this is a solid, feasible plan that matches your architecture perfectly.

---

## Gas Station / Convenience Store Considerations

- **High-frequency items:** Fuel prices can change multiple times daily; 5–15 min polling is acceptable.
- **Large SKU counts:** 500–2000 SKUs per store; use pagination (limit=100, offset) and rate limiting between pages.
- **Tobacco / alcohol:** Clover may set `hidden: true` for age-restricted items. Treat as delete for ESL (remove from labels); do not treat as error.
- **Variable pricing:** `priceType: "VARIABLE"` or `"PER_UNIT"` — store in `normalized_data`/`extra_data` if needed; transformer already converts price (cents → dollars).
- **Cost field:** Clover `cost` is in cents; convert to dollars in transformer if exposing as `unit_cost` in extra_data.

---

## Post-Implementation Testing Checklist

After implementation, verify:

1. [ ] **Create:** Create a test item in Clover → it appears in DB and syncs to Hipoink within one poll interval (e.g. 5 min).
2. [ ] **Update:** Change price or name in Clover → updates in DB and sync to Hipoink on next poll.
3. [ ] **Delete:** Delete item in Clover → within 24 hours (or next ghost cleanup) item is marked deleted and queued for ESL removal.
4. [ ] **Hidden:** Hide item in Clover → treated as delete (removed from DB/queue/ESL).
5. [ ] **Multi-merchant:** Two store mappings (two merchants) → each syncs independently with its own `last_sync_time` and no cross-talk.
6. [ ] **First run:** New store mapping with no `clover_last_sync_time` → first poll fetches all items (modified_since=0).
