"""Process inventory reservation commands for a single SKU."""

import sys
from dataclasses import dataclass
from itertools import islice
from typing import BinaryIO, TextIO

MAX_QUANTITY = 10**12
MAX_COMMANDS = 200_000
ORDER_ACTIONS = {b"RESERVE", b"RELEASE", b"SHIP"}


@dataclass(frozen=True)
class Command:
    action: bytes
    event_id: str
    quantity: int
    order_id: str | None = None


class Ledger:
    def __init__(self, initial_stock: int) -> None:
        self.on_hand = initial_stock
        self.reserved = 0
        self._reservations: dict[str, int] = {}
        self._processed_events: set[str] = set()

    def apply(self, command: Command) -> str:
        if command.event_id in self._processed_events:
            return "DUPLICATE"

        # A valid command consumes its event ID even if inventory rules reject it.
        self._processed_events.add(command.event_id)
        quantity = command.quantity
        if command.action == b"RESTOCK":
            self.on_hand += quantity
            return "OK"

        order_id = command.order_id
        assert order_id is not None
        order_reserved = self._reservations.get(order_id, 0)
        if command.action == b"RESERVE":
            if quantity > self.on_hand - self.reserved:
                return "REJECTED"
            self._reservations[order_id] = order_reserved + quantity
            self.reserved += quantity
            return "OK"

        if quantity > order_reserved:
            return "REJECTED"

        remaining = order_reserved - quantity
        if remaining:
            self._reservations[order_id] = remaining
        else:
            del self._reservations[order_id]
        self.reserved -= quantity
        if command.action == b"SHIP":
            self.on_hand -= quantity
        return "OK"

    def open_reservations(self) -> list[tuple[str, int]]:
        return sorted(self._reservations.items())


def _parse_uint(token: bytes, maximum: int) -> int | None:
    if not token.isdigit():
        return None
    digits = token.lstrip(b"0") or b"0"
    if len(digits) > len(str(maximum)):
        return None
    value = int(digits)
    return value if value <= maximum else None


def _parse_command(line: bytes) -> Command | None:
    fields = line.split()
    if len(fields) == 3 and fields[0] == b"RESTOCK":
        action, event, quantity_token = fields
        order = None
    elif len(fields) == 4 and fields[0] in ORDER_ACTIONS:
        action, event, order, quantity_token = fields
    else:
        return None

    quantity = _parse_uint(quantity_token, MAX_QUANTITY)
    if not quantity or not event.isascii() or (order is not None and not order.isascii()):
        return None

    order_id = order.decode("ascii") if order is not None else None
    return Command(action, event.decode("ascii"), quantity, order_id)


def _read_batch(stdin: BinaryIO) -> tuple[int, list[bytes]]:
    header = stdin.readline().split()
    if len(header) != 2:
        raise ValueError("expected initial stock and command count on the first line")
    initial_stock = _parse_uint(header[0], MAX_QUANTITY)
    command_count = _parse_uint(header[1], MAX_COMMANDS)
    if initial_stock is None or not command_count:
        raise ValueError("initial stock or command count is invalid")

    # Verify the command count before executing any command or writing stdout.
    commands = list(islice(stdin, command_count))
    if len(commands) != command_count or any(line.split() for line in stdin):
        raise ValueError(f"expected exactly {command_count} command lines")
    return initial_stock, commands


def run(stdin: BinaryIO, stdout: TextIO, stderr: TextIO) -> int:
    try:
        initial_stock, commands = _read_batch(stdin)
    except ValueError as error:
        print(f"Input error: {error}", file=stderr)
        return 1

    ledger = Ledger(initial_stock)
    for line in commands:
        command = _parse_command(line)
        status = "REJECTED" if command is None else ledger.apply(command)
        print(status, ledger.on_hand, ledger.reserved, file=stdout)

    open_orders = ledger.open_reservations()
    print("OPEN", len(open_orders), file=stdout)
    for order_id, quantity in open_orders:
        print(order_id, quantity, file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.stdin.buffer, sys.stdout, sys.stderr))
