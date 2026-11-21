from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
import logging
import os
from pathlib import Path
import sqlite3
from typing import Annotated

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .schemas import AddCartItem, AddCartResult, Cart, ErrorBody, ErrorResponse, Product
from .store import Store, StoreError

ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = ROOT / "data" / "shop.sqlite3"
CART_COOKIE = "pdp_cart"
CART_CONTEXT_HEADER = "X-Cart-Context"
logger = logging.getLogger(__name__)


def cart_context(cart_id: str) -> str:
    return sha256(cart_id.encode("utf-8")).hexdigest()


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(body.model_dump(exclude_none=True), status_code=status, headers={"Cache-Control": "no-store"})


def create_app(database_path: Path | None = None) -> FastAPI:
    if database_path is None:
        database_path = Path(os.getenv("PDP_DB_PATH", str(DEFAULT_DATABASE)))
    store = Store(database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialise()
        yield

    api = FastAPI(
        title="Variant PDP API",
        lifespan=lifespan,
        responses={
            500: {"model": ErrorResponse, "description": "Unexpected server error"},
            503: {
                "model": ErrorResponse,
                "description": "Database temporarily busy",
                "headers": {"Retry-After": {"description": "Wait time in seconds", "schema": {"type": "integer"}}},
            },
        },
    )

    @api.exception_handler(StoreError)
    async def handle_store_error(_: Request, exc: StoreError) -> JSONResponse:
        return error_response(exc.status, exc.code, str(exc), exc.details)

    @api.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        issues = [
            {"location": list(issue["loc"]), "message": issue["msg"], "type": issue["type"]}
            for issue in exc.errors()
        ]
        return error_response(422, "validation_error", "The request is invalid.", {"fields": issues})

    @api.exception_handler(sqlite3.OperationalError)
    async def handle_database_error(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        sqlite_code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if sqlite_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            response = error_response(503, "database_busy", "The store is busy. Please retry shortly.")
            response.headers["Retry-After"] = "1"
            return response
        return await handle_unexpected_error(request, exc)

    @api.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unexpected PDP API error", exc_info=exc)
        return error_response(500, "internal_error", "An unexpected error occurred.")

    @api.get("/api/products/{id}", responses={404: {"model": ErrorResponse, "description": "Unknown product"}})
    def get_product(id: str, response: Response) -> Product:
        response.headers["Cache-Control"] = "no-store"
        return store.get_product(id)

    @api.get(
        "/api/cart",
        responses={
            200: {
                "headers": {
                    CART_CONTEXT_HEADER: {
                        "description": "Cart context to echo on add requests",
                        "schema": {"type": "string"},
                    },
                },
            },
        },
    )
    def get_cart(request: Request, response: Response) -> Cart:
        response.headers["Cache-Control"] = "no-store"
        cart_id = request.cookies.get(CART_COOKIE)
        if cart_id:
            existing_cart = store.get_cart(cart_id)
            if existing_cart is not None:
                response.headers[CART_CONTEXT_HEADER] = cart_context(cart_id)
                return existing_cart

        cart_id = store.create_cart()
        response.set_cookie(
            CART_COOKIE,
            cart_id,
            path="/api",
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        response.headers[CART_CONTEXT_HEADER] = cart_context(cart_id)
        return Cart(items=[], total_item_count=0)

    @api.post(
        "/api/cart/items",
        responses={
            200: {
                "headers": {
                    "Idempotency-Replayed": {
                        "description": "Present with value true if this is a replay",
                        "schema": {"type": "string", "enum": ["true"]},
                    },
                },
            },
            404: {"model": ErrorResponse, "description": "Unknown SKU"},
            409: {"model": ErrorResponse, "description": "SKU, stock, idempotency key or cart context conflict"},
            422: {"model": ErrorResponse, "description": "Invalid request or missing cart session"},
        },
    )
    def add_item(
        item: AddCartItem,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")],
        expected_cart: Annotated[str | None, Header(alias=CART_CONTEXT_HEADER, pattern=r"^[a-f0-9]{64}$")] = None,
    ) -> AddCartResult:
        response.headers["Cache-Control"] = "no-store"
        cart_id = request.cookies.get(CART_COOKIE)
        # The cookie authorizes access. The context prevents a stale page from writing to another cart.
        if expected_cart is not None and (cart_id is None or cart_context(cart_id) != expected_cart):
            raise StoreError(409, "cart_context_changed", "The cart session has changed. Load the current cart.")
        result, replayed = store.add_item(cart_id, key, item)
        if replayed:
            response.headers["Idempotency-Replayed"] = "true"
        return result

    api.mount("/images", StaticFiles(directory=ROOT / "images"), name="images")
    return api


app = create_app()
