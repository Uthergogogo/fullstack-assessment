import asyncio
from collections.abc import Awaitable
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient, Response

from app.backend.main import CART_CONTEXT_HEADER, CART_COOKIE, create_app
from app.backend.store import Store

PRODUCT_URL = "/api/products/silt-mug"
CART_URL = "/api/cart"
ITEM_URL = f"{CART_URL}/items"
OAT = "mug-oat-250"
LAST_UNIT = "mug-moss-350"


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "shop.sqlite3"
        self.api = create_app(self.db_path)
        await self.enterAsyncContext(self.api.router.lifespan_context(self.api))
        self.client = await self.new_client()

    async def new_client(self) -> AsyncClient:
        return await self.enterAsyncContext(
            AsyncClient(
                transport=ASGITransport(app=self.api, raise_app_exceptions=False),
                base_url="http://testserver",
            )
        )

    async def post_item(
        self, client: AsyncClient, key: str, sku: str = OAT, quantity: int = 1, *, cart_context: str | None = None
    ) -> Response:
        headers = {"Idempotency-Key": key}
        if cart_context is not None:
            headers[CART_CONTEXT_HEADER] = cart_context
        return await client.post(ITEM_URL, headers=headers, json={"sku_id": sku, "quantity": quantity})

    async def stock(self, sku_id: str) -> int:
        product = (await self.client.get(PRODUCT_URL)).json()
        return next(sku["available_quantity"] for sku in product["skus"] if sku["id"] == sku_id)

    async def test_product_has_variants_and_served_images(self) -> None:
        response = await self.client.get(PRODUCT_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        product = response.json()
        self.assertEqual([option["id"] for option in product["options"]], ["color", "size"])
        self.assertEqual(product["currency"], "AUD")
        skus = {sku["id"]: sku for sku in product["skus"]}
        self.assertEqual(len(skus), 8)
        self.assertNotIn("mug-ink-450", skus)
        self.assertFalse(skus["mug-moss-450"]["is_available"])
        self.assertTrue(skus["mug-ink-250"]["is_available"])
        self.assertEqual(skus["mug-ink-250"]["available_quantity"], 0)
        self.assertEqual(skus[LAST_UNIT]["available_quantity"], 1)
        images = {sku["image_url"] for sku in skus.values()}
        self.assertEqual(len(images), len(skus))
        for image_url in images:
            with self.subTest(image_url=image_url):
                image = await self.client.get(image_url)
                self.assertEqual(image.status_code, 200)
                self.assertTrue(image.headers["content-type"].startswith("image/"))

    async def test_add_uses_server_price_updates_stock_and_merges_lines(self) -> None:
        cart = await self.client.get(CART_URL)
        self.assertEqual(cart.json(), {"items": [], "total_item_count": 0})
        self.assertIn(CART_COOKIE, cart.cookies)
        self.assertIn("HttpOnly", cart.headers["Set-Cookie"])
        self.assertIn("SameSite=lax", cart.headers["Set-Cookie"])

        first = await self.post_item(self.client, "first-add", quantity=2)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {
            "cart": {
                "items": [{"sku_id": OAT, "quantity": 2, "unit_price_minor": 2400, "currency": "AUD"}],
                "total_item_count": 2,
            },
            "sku_id": OAT,
            "available_quantity": 6,
        })

        self.assertEqual((await self.post_item(self.client, "another-add")).status_code, 200)
        cart = (await self.client.get(CART_URL)).json()
        self.assertEqual(cart["total_item_count"], 3)
        self.assertEqual([item["quantity"] for item in cart["items"]], [3])
        self.assertEqual(await self.stock(OAT), 5)

    async def test_invalid_payload_or_key_returns_structured_validation_errors(self) -> None:
        await self.client.get(CART_URL)
        valid = {"sku_id": OAT, "quantity": 1}
        cases = [({"Idempotency-Key": "check"}, {**valid, "quantity": qty})
                 for qty in (0, -1, True, 1.0, "1", 2**31)]
        cases.extend([
            ({"Idempotency-Key": "check"}, {**valid, "price_minor": 1}),
            ({"Idempotency-Key": "check"}, {**valid, "available_quantity": 10}),
            ({"Idempotency-Key": "check"}, {"quantity": 1}),
            ({"Idempotency-Key": "check"}, {**valid, "sku_id": "   "}),
            ({}, valid),
            ({"Idempotency-Key": ""}, valid),
            ({"Idempotency-Key": "a" * 129}, valid),
            ({"Idempotency-Key": "check", CART_CONTEXT_HEADER: "invalid"}, valid),
        ])
        for headers, payload in cases:
            with self.subTest(headers=headers, payload=payload):
                response = await self.client.post(ITEM_URL, json=payload, headers=headers)
                self.assertEqual(response.status_code, 422)
                error = response.json()["error"]
                self.assertEqual(error["code"], "validation_error")
                self.assertTrue(error["details"]["fields"])
        malformed = await self.client.post(
            ITEM_URL, content="{", headers={"Content-Type": "application/json", "Idempotency-Key": "check"}
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(await self.stock(OAT), 8)
        self.assertEqual((await self.post_item(self.client, "check")).status_code, 200)

    async def test_cart_session_must_be_established_before_post(self) -> None:
        response = await self.post_item(self.client, "session")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "cart_session_required")
        self.assertEqual(await self.stock(OAT), 8)
        await self.client.get(CART_URL)
        self.assertEqual((await self.post_item(self.client, "session")).status_code, 200)

    async def test_missing_disabled_and_out_of_stock_are_distinct(self) -> None:
        await self.client.get(CART_URL)
        missing_product = await self.client.get("/api/products/missing")
        self.assertEqual(missing_product.status_code, 404)
        self.assertEqual(missing_product.json()["error"]["code"], "product_not_found")

        for sku, status, code in (
            ("mug-ink-450", 404, "sku_not_found"),
            ("mug-moss-450", 409, "sku_unavailable"),
            ("mug-ink-250", 409, "insufficient_stock"),
        ):
            with self.subTest(sku=sku):
                response = await self.post_item(self.client, "stock-check", sku)
                self.assertEqual(response.status_code, status)
                error = response.json()["error"]
                self.assertEqual(error["code"], code)
                if code == "insufficient_stock":
                    self.assertEqual(error["details"], {"sku_id": sku, "available_quantity": 0})
        self.assertEqual((await self.client.get(CART_URL)).json()["total_item_count"], 0)
        self.assertEqual((await self.post_item(self.client, "stock-check", LAST_UNIT)).status_code, 200)

    async def test_replay_returns_original_response_and_rejects_changed_payload(self) -> None:
        await self.client.get(CART_URL)
        first = await self.post_item(self.client, "original", quantity=2)
        self.assertEqual(first.status_code, 200)
        self.assertEqual((await self.post_item(self.client, "later")).status_code, 200)

        replay = await self.post_item(self.client, "original", quantity=2)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.headers["Idempotency-Replayed"], "true")
        self.assertEqual(replay.json(), first.json())
        conflict = await self.post_item(self.client, "original", quantity=1)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(await self.stock(OAT), 5)

    async def test_carts_scope_idempotency_keys_and_share_stock(self) -> None:
        other = await self.new_client()
        await self.client.get(CART_URL)
        await other.get(CART_URL)
        self.assertEqual((await self.post_item(self.client, "same", quantity=2)).status_code, 200)
        self.assertEqual((await self.post_item(other, "same", quantity=1)).status_code, 200)
        self.assertEqual((await self.client.get(CART_URL)).json()["total_item_count"], 2)
        self.assertEqual((await other.get(CART_URL)).json()["total_item_count"], 1)
        self.assertEqual(await self.stock(OAT), 5)

    async def test_late_cart_cookie_cannot_replay_a_write_into_another_cart(self) -> None:
        other = await self.new_client()
        original_cart, late_cart = await asyncio.gather(self.client.get(CART_URL), other.get(CART_URL))
        original_context = original_cart.headers[CART_CONTEXT_HEADER]
        late_context = late_cart.headers[CART_CONTEXT_HEADER]
        self.assertNotEqual(original_context, late_context)
        self.assertNotEqual(original_context, original_cart.cookies[CART_COOKIE])
        self.assertEqual((await self.client.get(CART_URL)).headers[CART_CONTEXT_HEADER], original_context)

        first = await self.post_item(self.client, "late-cookie", cart_context=original_context)
        self.assertEqual(first.status_code, 200)

        browser = await self.new_client()
        without_cookie = await self.post_item(browser, "late-cookie", cart_context=original_context)
        self.assertEqual(without_cookie.status_code, 409)
        browser.cookies.update(late_cart.cookies)
        retry = await self.post_item(browser, "late-cookie", cart_context=original_context)
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["error"]["code"], "cart_context_changed")
        self.assertEqual((await browser.get(CART_URL)).json()["total_item_count"], 0)
        self.assertEqual(await self.stock(OAT), 7)

        replay = await self.post_item(self.client, "late-cookie", cart_context=original_context)
        self.assertEqual(replay.headers["Idempotency-Replayed"], "true")
        self.assertEqual(replay.json(), first.json())

    async def test_openapi_documents_the_custom_error_envelope_and_headers(self) -> None:
        contract = (await self.client.get("/openapi.json")).json()
        cart = contract["paths"][CART_URL]["get"]["responses"]
        add = contract["paths"][ITEM_URL]["post"]["responses"]
        self.assertIn(CART_CONTEXT_HEADER, cart["200"]["headers"])
        self.assertIn("Idempotency-Replayed", add["200"]["headers"])
        self.assertIn("Retry-After", add["503"]["headers"])
        for status in (404, 409, 422, 500, 503):
            with self.subTest(status=status):
                schema = add[str(status)]["content"]["application/json"]["schema"]
                self.assertEqual(schema["$ref"], "#/components/schemas/ErrorResponse")
        self.assertIn("error", contract["components"]["schemas"]["ErrorResponse"]["required"])

    async def test_last_unit_is_reserved_once_by_two_concurrent_carts(self) -> None:
        other = await self.new_client()
        await self.client.get(CART_URL)
        await other.get(CART_URL)
        first, second = await self.race(
            self.post_item(self.client, "first", LAST_UNIT), self.post_item(other, "second", LAST_UNIT)
        )
        self.assertEqual(sorted([first.status_code, second.status_code]), [200, 409])
        rejected = first if first.status_code == 409 else second
        self.assertEqual(rejected.json()["error"]["code"], "insufficient_stock")
        self.assertEqual(rejected.json()["error"]["details"]["available_quantity"], 0)
        quantities = [(await client.get(CART_URL)).json()["total_item_count"] for client in (self.client, other)]
        self.assertEqual(sorted(quantities), [0, 1])
        self.assertEqual(await self.stock(LAST_UNIT), 0)

    async def test_concurrent_replays_write_only_once(self) -> None:
        await self.client.get(CART_URL)
        first, second = await self.race(
            self.post_item(self.client, "dedupe", LAST_UNIT), self.post_item(self.client, "dedupe", LAST_UNIT)
        )
        self.assertEqual([first.status_code, second.status_code], [200, 200])
        self.assertEqual(first.json(), second.json())
        headers = [response.headers.get("Idempotency-Replayed", "") for response in (first, second)]
        self.assertEqual(sorted(headers), ["", "true"])
        self.assertEqual((await self.client.get(CART_URL)).json()["total_item_count"], 1)
        self.assertEqual(await self.stock(LAST_UNIT), 0)

    async def race(self, first: Awaitable[Response], second: Awaitable[Response]) -> list[Response]:
        connect = Store._connect
        barrier = Barrier(2, timeout=5)

        def connect_together(store: Store) -> sqlite3.Connection:
            # Each HTTP request obtains its own real connection before either attempts BEGIN.
            connection = connect(store)
            try:
                barrier.wait()
            except Exception:
                connection.close()
                raise
            return connection

        with patch.object(Store, "_connect", connect_together):
            return await asyncio.gather(first, second)

    async def test_idempotency_and_stock_survive_application_restart(self) -> None:
        await self.client.get(CART_URL)
        first = await self.post_item(self.client, "restart", LAST_UNIT)
        self.assertEqual(first.status_code, 200)

        self.api = create_app(self.db_path)
        await self.enterAsyncContext(self.api.router.lifespan_context(self.api))
        restarted = await self.new_client()
        restarted.cookies.update(self.client.cookies)
        replay = await self.post_item(restarted, "restart", LAST_UNIT)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(replay.headers["Idempotency-Replayed"], "true")
        self.assertEqual((await restarted.get(CART_URL)).json()["total_item_count"], 1)
        product = (await restarted.get(PRODUCT_URL)).json()
        self.assertEqual(next(sku for sku in product["skus"] if sku["id"] == LAST_UNIT)["available_quantity"], 0)

    async def test_failure_saving_idempotency_rolls_back_cart_and_stock(self) -> None:
        await self.client.get(CART_URL)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("""
                CREATE TRIGGER fail_record BEFORE INSERT ON idempotency_records
                BEGIN SELECT RAISE(ABORT, 'forced test failure'); END
            """)
        with self.assertLogs("app.backend.main", level="ERROR"):
            failed = await self.post_item(self.client, "rollback", LAST_UNIT)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json(), {"error": {"code": "internal_error", "message": "An unexpected error occurred."}})
        self.assertEqual((await self.client.get(CART_URL)).json()["total_item_count"], 0)
        self.assertEqual(await self.stock(LAST_UNIT), 1)

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DROP TRIGGER fail_record")
        retried = await self.post_item(self.client, "rollback", LAST_UNIT)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["cart"]["total_item_count"], 1)

    async def test_database_lock_timeout_returns_retryable_error(self) -> None:
        await self.client.get(CART_URL)
        connect = Store._connect

        def connect_with_short_timeout(store: Store) -> sqlite3.Connection:
            connection = connect(store)
            connection.execute("PRAGMA busy_timeout = 20")
            return connection

        with closing(sqlite3.connect(self.db_path)) as held_lock:
            held_lock.execute("BEGIN IMMEDIATE")
            with patch.object(Store, "_connect", connect_with_short_timeout):
                failed = await self.post_item(self.client, "busy")

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.headers["Retry-After"], "1")
        self.assertEqual(failed.json()["error"]["code"], "database_busy")
        self.assertEqual((await self.post_item(self.client, "busy")).status_code, 200)
        self.assertEqual(await self.stock(OAT), 7)
