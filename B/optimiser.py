"""Find an exact fulfilment split across warehouses."""

from collections import deque
from dataclasses import dataclass
import sys
from typing import TextIO

MAX_WAREHOUSES = 30
MAX_UNITS = 2_000
MAX_COST = 10**6

Score = tuple[int, int]


@dataclass(frozen=True)
class Warehouse:
    warehouse_id: str
    stock: int
    fixed_cost: int
    unit_cost: int


@dataclass(frozen=True)
class Solution:
    total_cost: int
    allocations: tuple[tuple[str, int], ...]


def _add_warehouse(warehouse: Warehouse, later: list[Score | None]) -> list[Score | None]:
    best = later.copy()  # Using zero units skips this warehouse at no cost.
    candidates: deque[tuple[int, Score]] = deque()

    for amount in range(1, len(later)):
        previous_amount = amount - 1
        previous_score = later[previous_amount]
        if previous_score is not None:
            used, cost = previous_score
            # For this amount, every candidate gains the same warehouse and
            # fixed_cost + amount * unit_cost. Compare the remaining terms.
            adjusted = (used, cost - previous_amount * warehouse.unit_cost)
            while candidates and candidates[-1][1] >= adjusted:
                candidates.pop()
            candidates.append((previous_amount, adjusted))

        while candidates and candidates[0][0] < amount - warehouse.stock:
            candidates.popleft()
        if candidates:
            used, adjusted_cost = candidates[0][1]
            use = (used + 1, adjusted_cost + warehouse.fixed_cost + amount * warehouse.unit_cost)
            skip = best[amount]
            if skip is None or use < skip:
                best[amount] = use

    return best


def optimise(warehouses: list[Warehouse], requested: int) -> Solution | None:
    """Return the best exact allocation for validated warehouses and demand."""
    ordered = sorted(warehouses, key=lambda warehouse: warehouse.warehouse_id)

    # The empty suffix can only supply zero units.
    suffix_scores: list[list[Score | None]] = [[(0, 0)] + [None] * requested]
    for warehouse in reversed(ordered):
        suffix_scores.append(_add_warehouse(warehouse, suffix_scores[-1]))
    suffix_scores.reverse()

    optimum = suffix_scores[0][requested]
    if optimum is None:
        return None

    allocations: list[tuple[str, int]] = []
    remaining = requested
    for index, warehouse in enumerate(ordered):
        if remaining == 0:
            break
        target = suffix_scores[index][remaining]
        later = suffix_scores[index + 1]
        for quantity in range(1, min(warehouse.stock, remaining) + 1):
            remainder = later[remaining - quantity]
            if remainder is None:
                continue
            used, cost = remainder
            score = (used + 1, cost + warehouse.fixed_cost + quantity * warehouse.unit_cost)
            if score == target:
                # Prefer the earliest ID and then the smallest quantity that
                # still allow an optimal completion.
                allocations.append((warehouse.warehouse_id, quantity))
                remaining -= quantity
                break

    assert remaining == 0
    return Solution(optimum[1], tuple(allocations))


def _integer(token: str, minimum: int, maximum: int, field: str) -> int:
    digits = token.lstrip("0") or "0"
    if token.isascii() and token.isdecimal() and len(digits) <= len(str(maximum)):
        value = int(digits)
        if minimum <= value <= maximum:
            return value
    raise ValueError(f"{field} must be a decimal integer from {minimum} to {maximum}")


def _read_problem(stdin: TextIO) -> tuple[list[Warehouse], int]:
    header = stdin.readline().split()
    if len(header) != 2:
        raise ValueError("expected warehouse count and requested quantity on the first line")
    count = _integer(header[0], 1, MAX_WAREHOUSES, "warehouse count")
    requested = _integer(header[1], 1, MAX_UNITS, "requested quantity")

    warehouses: list[Warehouse] = []
    seen_ids: set[str] = set()
    for row in range(1, count + 1):
        fields = stdin.readline().split()
        if len(fields) != 4:
            raise ValueError(f"expected ID, stock, fixed cost and unit cost on warehouse row {row}")
        warehouse_id, stock, fixed_cost, unit_cost = fields
        if warehouse_id in seen_ids:
            raise ValueError(f"duplicate warehouse ID on row {row}")
        seen_ids.add(warehouse_id)
        warehouses.append(
            Warehouse(
                warehouse_id,
                _integer(stock, 0, MAX_UNITS, "stock"),
                _integer(fixed_cost, 0, MAX_COST, "fixed cost"),
                _integer(unit_cost, 0, MAX_COST, "unit cost"),
            )
        )

    if any(line.split() for line in stdin):
        raise ValueError(f"expected exactly {count} warehouse rows")
    return warehouses, requested


def run(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    try:
        warehouses, requested = _read_problem(stdin)
    except ValueError as error:
        print(f"Input error: {error}", file=stderr)
        return 1

    solution = optimise(warehouses, requested)
    if solution is None:
        print(-1, file=stdout)
        return 0

    print(len(solution.allocations), solution.total_cost, file=stdout)
    for warehouse_id, quantity in solution.allocations:
        print(warehouse_id, quantity, file=stdout)
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(run(sys.stdin, sys.stdout, sys.stderr))
