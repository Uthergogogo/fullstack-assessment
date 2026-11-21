from io import StringIO
from itertools import product
from random import Random
import unittest

from B.optimiser import Solution, Warehouse, optimise, run


def run_problem(data: str) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    status = run(StringIO(data), stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def exhaustive_solution(warehouses: list[Warehouse], requested: int) -> Solution | None:
    best = None
    for quantities in product(*(range(warehouse.stock + 1) for warehouse in warehouses)):
        if sum(quantities) != requested:
            continue
        used = [(warehouse, qty) for warehouse, qty in zip(warehouses, quantities) if qty]
        cost = sum(warehouse.fixed_cost + qty * warehouse.unit_cost for warehouse, qty in used)
        allocation = tuple(sorted((warehouse.warehouse_id, qty) for warehouse, qty in used))
        candidate = (len(used), cost, allocation)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else Solution(best[1], best[2])


class OptimiserTests(unittest.TestCase):
    def test_assessment_example(self) -> None:
        data = "3 7\nAU 5 8 2\nCN 7 20 1\nUS 4 3 4\n"
        self.assertEqual(run_problem(data), (0, "1 27\nCN 7\n", ""))

    def test_warehouse_count_takes_priority_over_cost(self) -> None:
        warehouses = [Warehouse("A", 2, 0, 0), Warehouse("B", 2, 0, 0), Warehouse("C", 4, 10, 1)]
        self.assertEqual(optimise(warehouses, 4), Solution(14, (("C", 4),)))

    def test_cost_takes_priority_over_earlier_warehouse_id(self) -> None:
        warehouses = [Warehouse("A", 2, 10, 0), Warehouse("B", 2, 1, 1)]
        self.assertEqual(optimise(warehouses, 2), Solution(3, (("B", 2),)))

    def test_unit_cost_changes_the_split_between_used_warehouses(self) -> None:
        warehouses = [Warehouse("A", 3, 3, 1), Warehouse("B", 3, 0, 5)]
        self.assertEqual(optimise(warehouses, 5), Solution(16, (("A", 3), ("B", 2))))

    def test_equal_cost_prefers_earliest_ids_and_smallest_feasible_quantity(self) -> None:
        warehouses = [Warehouse(warehouse_id, 3, 1, 2) for warehouse_id in ("C", "B", "A")]
        self.assertEqual(optimise(warehouses, 4), Solution(10, (("A", 1), ("B", 3))))

    def test_zero_stock_warehouse_cannot_be_used(self) -> None:
        warehouses = [Warehouse("A", 0, 0, 0), Warehouse("B", 3, 4, 2)]
        self.assertEqual(optimise(warehouses, 3), Solution(10, (("B", 3),)))

    def test_insufficient_total_stock_outputs_minus_one(self) -> None:
        self.assertEqual(run_problem("2 4\nA 0 0 0\nB 3 4 2\n"), (0, "-1\n", ""))

    def test_large_demand_and_many_tied_warehouses(self) -> None:
        warehouses = [Warehouse(f"W{i:02d}", 101, 10**6, 10**6) for i in range(30)]
        expected = (("W00", 81),) + tuple((f"W{i:02d}", 101) for i in range(1, 20))
        self.assertEqual(optimise(warehouses, 2_000), Solution(2_020_000_000, expected))

    def test_malformed_inputs_are_distinct_from_impossible_orders(self) -> None:
        invalid_inputs = (
            "",
            "31 1\n",
            "1 0\n",
            "1 2001\n",
            "1 1\nA 2001 0 0\n",
            "1 1\nA 1 1000001 0\n",
            "1 1\nA 1 0 -1\n",
            "1 1\nA 1 0 ١\n",
            "1 1\nA 1 0\n",
            "2 1\nA 1 0 0\n",
            "1 1\nA 1 0 0\nB 1 0 0\n",
            "2 1\nA 1 0 0\nA 1 0 0\n",
        )
        for data in invalid_inputs:
            with self.subTest(data=data):
                status, stdout, stderr = run_problem(data)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("Input error: "), stderr)

    def test_ids_are_lexical_and_case_sensitive(self) -> None:
        data = "3 01\r\nw2 1 0 0\r\nW2 1 0 0\r\nW10 1 0 0\r\n\r\n"
        self.assertEqual(run_problem(data), (0, "1 0\nW10 1\n", ""))

    def test_small_instances_match_exhaustive_search(self) -> None:
        rng = Random(29)
        for case in range(300):
            warehouses = [
                Warehouse(f"W{i}", rng.randrange(4), rng.randrange(5), rng.randrange(5))
                for i in range(rng.randint(1, 6))
            ]
            rng.shuffle(warehouses)
            requested = rng.randint(1, 15)
            with self.subTest(case=case, warehouses=warehouses, requested=requested):
                self.assertEqual(optimise(warehouses, requested), exhaustive_solution(warehouses, requested))
