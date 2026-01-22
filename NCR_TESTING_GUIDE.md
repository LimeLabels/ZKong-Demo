# NCR POS Integration Testing Guide

This guide provides step-by-step instructions for testing the NCR POS integration endpoints.

## Prerequisites

1. **Environment Variables Setup**
   - Ensure your `.env` file (or environment) has the following NCR credentials:
     ```
     NCR_API_BASE_URL=https://api.ncr.com/catalog
     NCR_SHARED_KEY=your_shared_key_here
     NCR_SECRET_KEY=your_secret_key_here
     NCR_ORGANIZATION=your_organization_id_here
     NCR_ENTERPRISE_UNIT=your_enterprise_unit_id_here
     NCR_DEPARTMENT_ID=DEFAULT
     NCR_CATEGORY_ID=DEFAULT
     ```

2. **Start the FastAPI Server**
   ```bash
   cd /Users/jaygadhia/Desktop/ESL\ Systems/ZKong-Demo
   python -m uvicorn app.main:app --reload --port 8000
   ```
   
   The server should start on `http://localhost:8000`

3. **Verify Server is Running**
   ```bash
   curl http://localhost:8000/health
   ```
   Expected response: `{"status":"healthy"}`

## Step 1: Verify Configuration

Before testing, verify that your NCR credentials are properly configured.

**Endpoint:** `GET /api/ncr/config`

**Using cURL:**
```bash
curl http://localhost:8000/api/ncr/config
```

**Using Python requests:**
```python
import requests

response = requests.get("http://localhost:8000/api/ncr/config")
print(response.json())
```

**Expected Response:**
```json
{
  "base_url": "https://api.ncr.com/catalog",
  "organization": "your-organization-id",
  "enterprise_unit": "your-enterprise-unit-id",
  "department_id": "DEFAULT",
  "category_id": "DEFAULT",
  "has_shared_key": true,
  "has_secret_key": true
}
```

**✅ Check:** All fields should be populated (not "(not set)") and both `has_shared_key` and `has_secret_key` should be `true`.

---

## Step 2: Test Product Creation

Create a new product in NCR.

**Endpoint:** `POST /api/ncr/test/create-product`

**Using cURL:**
```bash
curl -X POST http://localhost:8000/api/ncr/test/create-product \
  -H "Content-Type: application/json" \
  -d '{
    "item_code": "TEST-ITEM-001",
    "title": "Test Product",
    "price": 19.99,
    "sku": "SKU-001",
    "barcode": "123456789012",
    "department_id": "DEFAULT",
    "category_id": "DEFAULT"
  }'
```

**Using Python requests:**
```python
import requests

payload = {
    "item_code": "TEST-ITEM-001",
    "title": "Test Product",
    "price": 19.99,
    "sku": "SKU-001",
    "barcode": "123456789012",
    "department_id": "DEFAULT",
    "category_id": "DEFAULT"
}

response = requests.post(
    "http://localhost:8000/api/ncr/test/create-product",
    json=payload
)
print(response.status_code)
print(response.json())
```

**Expected Success Response (200):**
```json
{
  "status": "success",
  "message": "Product created successfully",
  "result": {
    "status": "success",
    "item_code": "TEST-ITEM-001"
  }
}
```

**✅ Check:**
- Status code: `200`
- Response contains `"status": "success"`
- Product should now be visible in your NCR demo store at `http://localhost:3000`

**Common Errors:**
- `401 Unauthorized`: Check your `NCR_SHARED_KEY` and `NCR_SECRET_KEY`
- `400 Bad Request`: Check that `item_code` is alphanumeric (max 100 chars)
- `404 Not Found`: Verify `NCR_ORGANIZATION` is correct

---

## Step 3: Test Price Update

Update the price of an existing product.

**Endpoint:** `POST /api/ncr/test/update-price`

**Using cURL:**
```bash
curl -X POST http://localhost:8000/api/ncr/test/update-price \
  -H "Content-Type: application/json" \
  -d '{
    "item_code": "TEST-ITEM-001",
    "price": 24.99,
    "price_code": "REGULAR",
    "currency": "USD"
  }'
```

**Using Python requests:**
```python
import requests

payload = {
    "item_code": "TEST-ITEM-001",
    "price": 24.99,
    "price_code": "REGULAR",
    "currency": "USD"
}

response = requests.post(
    "http://localhost:8000/api/ncr/test/update-price",
    json=payload
)
print(response.status_code)
print(response.json())
```

**Expected Success Response (200):**
```json
{
  "status": "success",
  "message": "Price updated successfully",
  "result": {
    "status": "success",
    "item_code": "TEST-ITEM-001",
    "price": 24.99
  }
}
```

**✅ Check:**
- Status code: `200`
- Response contains `"status": "success"`
- Price should be updated in NCR (verify in demo store)

**Note:** This endpoint requires `NCR_ENTERPRISE_UNIT` to be set. If you get an error about missing enterprise unit, check your configuration.

---

## Step 4: Test Product Deletion

Delete (deactivate) a product by setting its status to INACTIVE.

**Endpoint:** `POST /api/ncr/test/delete-product`

**Using cURL:**
```bash
curl -X POST http://localhost:8000/api/ncr/test/delete-product \
  -H "Content-Type: application/json" \
  -d '{
    "item_code": "TEST-ITEM-001",
    "department_id": "DEFAULT",
    "category_id": "DEFAULT"
  }'
```

**Using Python requests:**
```python
import requests

payload = {
    "item_code": "TEST-ITEM-001",
    "department_id": "DEFAULT",
    "category_id": "DEFAULT"
}

response = requests.post(
    "http://localhost:8000/api/ncr/test/delete-product",
    json=payload
)
print(response.status_code)
print(response.json())
```

**Expected Success Response (200):**
```json
{
  "status": "success",
  "message": "Product deleted (set to INACTIVE)",
  "result": {
    "status": "success",
    "item_code": "TEST-ITEM-001",
    "deleted": true
  }
}
```

**✅ Check:**
- Status code: `200`
- Response contains `"status": "success"` and `"deleted": true`
- Product should be marked as INACTIVE in NCR (may not appear in active product listings)

---

## Step 5: Verify in NCR Demo Store

After creating/updating products, verify them in your local NCR demo store:

1. **Open the demo store:**
   ```bash
   # In the ncr-retail-demo directory
   cd /Users/jaygadhia/Desktop/ESL\ Systems/ncr-retail-demo
   npm run dev
   # or
   yarn dev
   ```

2. **Navigate to:** `http://localhost:3000`

3. **Check the catalog:**
   - Products you created should appear in the catalog
   - Prices should match what you set
   - Deleted products should not appear (or appear as inactive)

---

## Complete Test Script

Here's a complete Python script to test all endpoints:

```python
#!/usr/bin/env python3
"""
Complete NCR Integration Test Script
"""
import requests
import time
import json

BASE_URL = "http://localhost:8000"
TEST_ITEM_CODE = f"TEST-ITEM-{int(time.time())}"  # Unique item code

def test_config():
    """Test 1: Verify configuration"""
    print("\n=== Test 1: Configuration Check ===")
    response = requests.get(f"{BASE_URL}/api/ncr/config")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_create_product():
    """Test 2: Create a product"""
    print(f"\n=== Test 2: Create Product ({TEST_ITEM_CODE}) ===")
    payload = {
        "item_code": TEST_ITEM_CODE,
        "title": "Test Product from Integration",
        "price": 19.99,
        "sku": f"SKU-{int(time.time())}",
        "barcode": "123456789012",
        "department_id": "DEFAULT",
        "category_id": "DEFAULT"
    }
    response = requests.post(
        f"{BASE_URL}/api/ncr/test/create-product",
        json=payload
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_update_price():
    """Test 3: Update product price"""
    print(f"\n=== Test 3: Update Price ({TEST_ITEM_CODE}) ===")
    payload = {
        "item_code": TEST_ITEM_CODE,
        "price": 29.99,
        "price_code": "REGULAR",
        "currency": "USD"
    }
    response = requests.post(
        f"{BASE_URL}/api/ncr/test/update-price",
        json=payload
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

def test_delete_product():
    """Test 4: Delete product"""
    print(f"\n=== Test 4: Delete Product ({TEST_ITEM_CODE}) ===")
    payload = {
        "item_code": TEST_ITEM_CODE,
        "department_id": "DEFAULT",
        "category_id": "DEFAULT"
    }
    response = requests.post(
        f"{BASE_URL}/api/ncr/test/delete-product",
        json=payload
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200

if __name__ == "__main__":
    print("Starting NCR Integration Tests...")
    print(f"Base URL: {BASE_URL}")
    print(f"Test Item Code: {TEST_ITEM_CODE}")
    
    results = []
    results.append(("Configuration", test_config()))
    time.sleep(1)  # Small delay between requests
    
    results.append(("Create Product", test_create_product()))
    time.sleep(2)  # Wait for product to be created
    
    results.append(("Update Price", test_update_price()))
    time.sleep(1)
    
    results.append(("Delete Product", test_delete_product()))
    
    print("\n=== Test Summary ===")
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
```

**To run the test script:**
```bash
python test_ncr_integration.py
```

---

## Troubleshooting

### Common Issues

1. **"NCR API error 401: Unauthorized"**
   - Check that `NCR_SHARED_KEY` and `NCR_SECRET_KEY` are correct
   - Verify they match the values in your `.env.local` file
   - Ensure there are no extra spaces or quotes

2. **"NCR API error 400: Bad Request"**
   - Verify `item_code` is alphanumeric (no special characters except `-` and `_`)
   - Check that `department_id` and `category_id` exist in your NCR system
   - Ensure required fields are provided

3. **"NCR_ENTERPRISE_UNIT must be set"**
   - Set `NCR_ENTERPRISE_UNIT` in your `.env` file
   - This is required for price updates

4. **Connection errors**
   - Verify the FastAPI server is running on port 8000
   - Check network connectivity to `https://api.ncr.com`
   - Verify firewall settings

5. **HMAC signature errors**
   - Ensure system clock is synchronized (HMAC uses timestamps)
   - Check that date/time format matches NCR requirements

### Debug Mode

To see detailed logs, check the FastAPI server console output. The integration uses `structlog` for logging and will show:
- Request URLs and payloads
- HMAC signature generation details
- API response status codes and bodies
- Error messages with full context

---

## Next Steps

After successful testing:

1. **Integrate with your application:** Use the `NCRIntegrationAdapter` class in your application code
2. **Set up webhooks:** Configure NCR webhooks (if available) to sync changes back
3. **Monitor logs:** Set up log aggregation to monitor API calls
4. **Error handling:** Implement retry logic for transient failures
5. **Rate limiting:** Be aware of NCR API rate limits and implement throttling if needed

---

## API Documentation

- **Swagger UI:** Once the server is running, visit `http://localhost:8000/docs` for interactive API documentation
- **NCR API Docs:** See `bsp-items-catalog-v2_swagger.json` for complete NCR API specification

