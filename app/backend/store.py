from collections.abc import Iterator
from contextlib import closing, contextmanager
import json
from pathlib import Path
import secrets
import sqlite3

from .schemas import AddCartItem, AddCartResult, Cart, CartItem, Product, Sku
from .seed import seed_catalog


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    currency TEXT NOT NULL,
    options_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skus (
    id TEXT PRIMARY KEY NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(id),
    color TEXT NOT NULL,
    size TEXT NOT NULL,
    price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    image_url TEXT NOT NULL,
    is_available INTEGER NOT NULL CHECK (is_available IN (0, 1)),
    UNIQUE (product_id, color, size)
);
CREATE TABLE IF NOT EXISTS carts (
    id TEXT PRIMARY KEY NOT NULL
);
CREATE TABLE IF NOT EXISTS cart_items (
    cart_id TEXT NOT NULL REFERENCES carts(id),
    sku_id TEXT NOT NULL REFERENCES skus(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (cart_id, sku_id)
);
CREATE TABLE IF NOT EXISTS idempotency_records (
    cart_id TEXT NOT NULL REFERENCES carts(id),
    key TEXT NOT NULL,
    sku_id TEXT NOT NULL REFERENCES skus(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    response_json TEXT NOT NULL,
    PRIMARY KEY (cart_id, key)
);
"""


class StoreError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def initialise(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
        with self._write() as connection:
            seed_catalog(connection)

    def get_product(self, product_id: str) -> Product:
        with closing(self._connect()) as connection:
            product = connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if product is None:
                raise StoreError(404, "product_not_found", "Product not found.")
            rows = connection.execute(
                "SELECT * FROM skus WHERE product_id = ? ORDER BY id", (product_id,)
            ).fetchall()

        return Product(
            id=product["id"],
            name=product["name"],
            description=product["description"],
            currency=product["currency"],
            options=json.loads(product["options_json"]),
            skus=[
                Sku(
                    id=row["id"],
                    option_values={"color": row["color"], "size": row["size"]},
                    price_minor=row["price_minor"],
                    available_quantity=row["available_quantity"],
                    image_url=row["image_url"],
                    is_available=bool(row["is_available"]),
                )
                for row in rows
            ],
        )

    def create_cart(self) -> str:
        cart_id = secrets.token_hex(16)
        with self._write() as connection:
            connection.execute("INSERT INTO carts (id) VALUES (?)", (cart_id,))
        return cart_id

    def get_cart(self, cart_id: str) -> Cart | None:
        with closing(self._connect()) as connection:
            if not self._cart_exists(connection, cart_id):
                return None
            return self._read_cart(connection, cart_id)

    @staticmethod
    def _cart_exists(connection: sqlite3.Connection, cart_id: str) -> bool:
        return connection.execute("SELECT 1 FROM carts WHERE id = ?", (cart_id,)).fetchone() is not None

    @staticmethod
    def _read_cart(connection: sqlite3.Connection, cart_id: str) -> Cart:
        rows = connection.execute(
            """
            SELECT ci.sku_id, ci.quantity, s.price_minor AS unit_price_minor, p.currency
            FROM cart_items ci
            JOIN skus s ON s.id = ci.sku_id
            JOIN products p ON p.id = s.product_id
            WHERE ci.cart_id = ?
            ORDER BY ci.sku_id
            """,
            (cart_id,),
        )
        items = [CartItem.model_validate(dict(row)) for row in rows]
        return Cart(items=items, total_item_count=sum(item.quantity for item in items))

    def add_item(self, cart_id: str | None, key: str, item: AddCartItem) -> tuple[AddCartResult, bool]:
        with self._write() as connection:
            if cart_id is None or not self._cart_exists(connection, cart_id):
                raise StoreError(422, "cart_session_required", "Load the cart before adding items.")

            recorded = connection.execute(
                """
                SELECT sku_id, quantity, response_json FROM idempotency_records
                WHERE cart_id = ? AND key = ?
                """,
                (cart_id, key),
            ).fetchone()
            if recorded is not None:
                if (recorded["sku_id"], recorded["quantity"]) != (item.sku_id, item.quantity):
                    raise StoreError(
                        409, "idempotency_conflict", "This key was already used with different items or quantity."
                    )
                return AddCartResult.model_validate_json(recorded["response_json"]), True

            remaining = self._reserve_stock(connection, item)
            connection.execute(
                """
                INSERT INTO cart_items (cart_id, sku_id, quantity) VALUES (?, ?, ?)
                ON CONFLICT(cart_id, sku_id) DO UPDATE SET quantity = quantity + excluded.quantity
                """,
                (cart_id, item.sku_id, item.quantity),
            )
            result = AddCartResult(
                cart=self._read_cart(connection, cart_id), sku_id=item.sku_id, available_quantity=remaining
            )
            connection.execute(
                """
                INSERT INTO idempotency_records (cart_id, key, sku_id, quantity, response_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cart_id, key, item.sku_id, item.quantity, result.model_dump_json()),
            )
            return result, False

    @staticmethod
    def _reserve_stock(connection: sqlite3.Connection, item: AddCartItem) -> int:
        updated = connection.execute(
            """
            UPDATE skus SET available_quantity = available_quantity - ?
            WHERE id = ? AND is_available = 1 AND available_quantity >= ?
            """,
            (item.quantity, item.sku_id, item.quantity),
        )
        sku = connection.execute(
            "SELECT available_quantity, is_available FROM skus WHERE id = ?", (item.sku_id,)
        ).fetchone()
        if sku is None:
            raise StoreError(404, "sku_not_found", "SKU not found.")
        if not sku["is_available"]:
            raise StoreError(409, "sku_unavailable", "This combination is unavailable.")
        if updated.rowcount != 1:
            raise StoreError(
                409,
                "insufficient_stock",
                "There is not enough stock for the requested quantity.",
                {"sku_id": item.sku_id, "available_quantity": sku["available_quantity"]},
            )
        return sku["available_quantity"]
