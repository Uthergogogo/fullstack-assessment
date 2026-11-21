import json
from sqlite3 import Connection

PRODUCT_ID = "silt-mug"

OPTIONS = [
    {
        "id": "color",
        "label": "Glaze",
        "values": [
            {"id": "oat", "label": "Oat"},
            {"id": "moss", "label": "Moss"},
            {"id": "ink", "label": "Ink"},
        ],
    },
    {
        "id": "size",
        "label": "Capacity",
        "values": [
            {"id": "250", "label": "250 mL"},
            {"id": "350", "label": "350 mL"},
            {"id": "450", "label": "450 mL"},
        ],
    },
]

# color, capacity, price in cents, available quantity, active in the catalog
VARIANTS = (
    ("oat", "250", 2400, 8, True),
    ("oat", "350", 2800, 12, True),
    ("oat", "450", 3200, 4, True),
    ("moss", "250", 2500, 6, True),
    ("moss", "350", 2900, 1, True),
    ("moss", "450", 3300, 0, False),
    ("ink", "250", 2500, 0, True),
    ("ink", "350", 2900, 5, True),
)


def seed_catalog(connection: Connection) -> None:
    connection.execute(
        """
        INSERT INTO products (id, name, description, currency, options_json)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
        """,
        (
            PRODUCT_ID,
            "Silt Stoneware Mug",
            "A softly rounded ceramic mug with a satin glaze and an easy-grip handle.",
            "AUD",
            json.dumps(OPTIONS),
        ),
    )
    connection.executemany(
        """
        INSERT INTO skus (id, product_id, color, size, price_minor,
                          available_quantity, image_url, is_available)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
        """,
        (
            (f"mug-{color}-{size}", PRODUCT_ID, color, size, price, stock,
             f"/images/{color}-{size}.webp", active)
            for color, size, price, stock, active in VARIANTS
        ),
    )
