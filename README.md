# Full-Stack Developer Coding Assessment

- [A — Inventory Reservation Ledger](A/README.md) covers the command-line program, replay rules and complexity.
- [B — Fulfilment Split Optimiser](B/README.md) covers the command-line program, dynamic programming and tie-breaking.
- [C — Xero Integration Review](C/answers.md) contains the six written answers and official references.
- [App backend](app/backend/README.md) and [App frontend](app/frontend/README.md) document the product detail page and its API.
- [AI assistance disclosure](AI_USAGE.md) records where AI tools were used.

## Setup

Use Python 3.11+ and Node.js 22.12+. Run commands from the project root. In PowerShell, use `npm.cmd` for `npm`. On macOS or Linux, activate the virtual environment with `source .venv/bin/activate`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app/backend/requirements-dev.txt
npm.cmd --prefix app/frontend ci
```

Start the API in one terminal. On macOS or Linux, use `python` from the active virtual environment in place of the Windows Python path.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal. Then open [the product page](http://127.0.0.1:5173/).

```powershell
npm.cmd --prefix app/frontend run dev
```

The API seeds the sample product on startup. The [interactive API reference](http://127.0.0.1:8000/docs) is served by FastAPI. The Python dependency files are under `app/backend/`, and the Node manifest and lockfile are under `app/frontend/`. A and B use the Python standard library.

## Run and test

The task READMEs include runnable examples. Send input to `python -m A.ledger` or `python -m B.optimiser` via standard input.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s A -v
.\.venv\Scripts\python.exe -m unittest discover -s B -v
.\.venv\Scripts\python.exe -m unittest app.backend.test_api -v
npm.cmd --prefix app/frontend test
npm.cmd --prefix app/frontend run build
```

Tests run without starting either server. Backend tests use temporary SQLite databases. The frontend build command also runs the TypeScript checker.

## App API

- `GET /api/products/{id}` returns `200` with the product, option dimensions and SKU data. Try `/api/products/silt-mug`. Each SKU includes price in minor currency units, available quantity and an image path. The [example product response](app/backend/README.md#get-apiproductsid) shows both option dimensions and one SKU.
- `GET /api/cart` returns `200` with the current cart, its total unit count and an `X-Cart-Context` response header. A new cart starts with `{"items": [], "total_item_count": 0}` and sets the `pdp_cart` cookie.
- `POST /api/cart/items` accepts the cart cookie, an `Idempotency-Key` and a body such as `{"sku_id": "mug-oat-250", "quantity": 2}`. Echo `X-Cart-Context` from the cart read and retain it with the original key and body when retrying. A successful add returns `200`, the updated cart and the remaining stock. A replay of that add includes `Idempotency-Replayed: true`.

An add of two units to a new cart with the initial stock returns the following body.

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

Errors use `{"error": {"code": "…", "message": "…"}}` with optional `details`. Invalid requests or missing cart sessions return `422`. Unknown products or SKUs return `404`. Insufficient stock, unavailable SKUs, a reused key with different data or a changed cart context return `409`. Unexpected failures return `500`, and a database lock timeout returns `503` with `Retry-After`. See the [backend README](app/backend/README.md) for the request sequence and error details.

## Architecture and assumptions

- In **A**, a dictionary tracks reservations by order, and a set tracks processed event IDs. Malformed commands are rejected before consuming an ID. Valid commands that fail inventory rules still consume the ID.
- In **B**, a suffix dynamic programme minimises warehouse count and cost in `O(WQ)` time after sorting. Reconstruction chooses the smallest feasible allocation list in warehouse ID order.
- In the **App**, React and TypeScript resolve the selected SKU and quantity. Vite proxies `/api` and `/images` to FastAPI. The server validates the add against current inventory and uses SQLite `BEGIN IMMEDIATE` to commit the stock reservation, cart update and replay record together. Idempotency keys are scoped to a cart. The browser echoes the context it read with that cart so a late cookie change cannot redirect an outstanding add into another cart.

## Known limitations

SQLite serializes writers. The local demo reserves stock when items are added. Abandoned carts and their reservations persist indefinitely. Set `PDP_DB_PATH` to a new file before starting the API to restore the seeded demo state.

The browser keeps the original request for retry while the page is open. If the session cookie changes, it refreshes the current cart and stock and leaves any earlier reservation in the original cart. The App ends at add-to-cart, in keeping with the assessment scope.
