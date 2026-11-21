# Variant PDP backend

Run from the repository root with Python 3.11 or later. The API uses FastAPI, Pydantic, Uvicorn and the standard library's SQLite driver. The test requirements add HTTPX.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app/backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

The server seeds a sample product at startup. Open `http://127.0.0.1:8000/docs` for the interactive API schema. Run the tests in a second terminal from the repository root.

```powershell
.\.venv\Scripts\python.exe -m unittest app.backend.test_api -v
```

## API contract

The following PowerShell example starts an anonymous cart and adds two units to it. It uses the same session cookie and idempotency key to replay the request.

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod "$base/api/products/silt-mug"
$cart = Invoke-WebRequest "$base/api/cart" -SessionVariable pdpSession -UseBasicParsing
$cart.Content
$body = @{ sku_id = 'mug-oat-250'; quantity = 2 } | ConvertTo-Json -Compress
$headers = @{ 'Idempotency-Key' = [guid]::NewGuid().ToString(); 'X-Cart-Context' = @($cart.Headers['X-Cart-Context'])[0] }
Invoke-RestMethod "$base/api/cart/items" -Method Post -WebSession $pdpSession -Headers $headers -ContentType 'application/json' -Body $body
Invoke-RestMethod "$base/api/cart/items" -Method Post -WebSession $pdpSession -Headers $headers -ContentType 'application/json' -Body $body
Invoke-RestMethod "$base/api/cart" -WebSession $pdpSession
```

### `GET /api/products/{id}`

`200` returns the product name, description, currency, ordered option dimensions and SKU data. Each SKU includes its ID, option values, current inventory, availability, price in minor currency units and an image URL. Below is a representative excerpt taken from a fresh database.

```json
{
  "id": "silt-mug",
  "name": "Silt Stoneware Mug",
  "description": "A softly rounded ceramic mug with a satin glaze and an easy-grip handle.",
  "currency": "AUD",
  "options": [
    {"id": "color", "label": "Glaze", "values": [{"id": "oat", "label": "Oat"}]},
    {"id": "size", "label": "Capacity", "values": [{"id": "250", "label": "250 mL"}]}
  ],
  "skus": [
    {
      "id": "mug-oat-250",
      "option_values": {"color": "oat", "size": "250"},
      "price_minor": 2400,
      "available_quantity": 8,
      "image_url": "/images/oat-250.webp",
      "is_available": true
    }
  ]
}
```

The full dataset has eight SKUs. Ink / 450 mL has no SKU. Moss / 450 mL is disabled (`is_available: false`). Ink / 250 mL is an active SKU with zero stock. Moss / 350 mL starts with one unit. `/images/*` serves the local WebP files. The frontend can use a same-origin proxy for both `/api` and `/images` during development.

The fictional catalog images use the built-in ImageGen tool. The prompts specify a square studio photo of one empty, unbranded satin-glazed stoneware mug with mineral flecks and a right-facing loop handle, centered on an ivory backdrop with soft light from the upper left. They vary the glaze among oat, moss and charcoal navy and the silhouette among compact, rounded and tall.

### `GET /api/cart`

`200` returns the current items and total number of units. A client without a recognised cart receives a new `HttpOnly`, `SameSite=Lax` cookie named `pdp_cart` and the empty cart shown below. Keep the cookie for later requests. The `X-Cart-Context` response header identifies the cart associated with that response without exposing the cookie value.

```json
{"items": [], "total_item_count": 0}
```

### `POST /api/cart/items`

Send the cart cookie, an `Idempotency-Key` header, and the JSON body below. The header accepts 1–128 characters from letters, digits and `._:-`. The quantity must be a JSON integer in the range 1 to 2,147,483,647. The only body fields are `sku_id` and `quantity`. The server supplies prices and checks current stock.

Echo the `X-Cart-Context` header from `GET /api/cart` for browser clients and retain it with the key and body on retry. If the cookie points to a different cart or is missing, the server rejects the bound request before any write. Clients that manage a stable cookie directly may omit the context header. Their keys still apply within that cart.

```json
{"sku_id": "mug-oat-250", "quantity": 2}
```

`200` returns the updated cart and the affected SKU's remaining stock at the time of the add. Repeating a successful key with the same SKU and quantity within that cart returns the original `200` body and adds the header `Idempotency-Replayed: true`. Use the GET endpoints for fresh cart and stock data after a replay. Use a new key for a new add. Unsuccessful operations leave the key available.

```json
{
  "cart": {
    "items": [{"sku_id": "mug-oat-250", "quantity": 2, "unit_price_minor": 2400, "currency": "AUD"}],
    "total_item_count": 2
  },
  "sku_id": "mug-oat-250",
  "available_quantity": 6
}
```

### Errors

Errors use an `error` object with `code`, `message` and optional `details`.

- `422 validation_error` for malformed requests or missing/invalid keys. `details.fields` lists the invalid fields. `422 cart_session_required` asks the client to load the cart first.
- `404 product_not_found` or `sku_not_found` for unknown resources.
- `409 sku_unavailable` for a disabled SKU. `409 insufficient_stock` includes the affected SKU and current available quantity. `409 idempotency_conflict` means a successful key was reused with a different SKU or quantity.
- `409 cart_context_changed` means the supplied cart context no longer matches the cookie. Read the current cart and product before starting another add.
- `503 database_busy` for a SQLite lock timeout. `Retry-After: 1` tells the client when it can retry. `500 internal_error` reports an unexpected server failure without returning implementation details.

```json
{
  "error": {
    "code": "insufficient_stock",
    "message": "There is not enough stock for the requested quantity.",
    "details": {"sku_id": "mug-moss-350", "available_quantity": 0}
  }
}
```

## Persistence and concurrency

Each request opens its own SQLite connection. The add path acquires the write transaction with `BEGIN IMMEDIATE` before checking the cart and idempotency key. An `UPDATE` guarded by SKU availability and `available_quantity >= quantity` reserves stock. The stock update, cart upsert and original response record commit together. A second writer sees the completed result or the reduced stock. A failure before commit rolls back all three writes. [SQLite transaction documentation](https://www.sqlite.org/lang_transaction.html)

SQLite allows one writer at a time. This is sufficient for the demo and can become a throughput bottleneck under heavy writes. Cart adds reserve inventory immediately. The demo has no expiry, stock release or cleanup process for abandoned carts and idempotency records. The default database is `app/backend/data/shop.sqlite3` and survives server restarts. For a fresh demo, stop the server, set `PDP_DB_PATH` to a new database file path and restart. Tests use disposable database files.
