# Task B — Fulfilment Split Optimiser

Run from the repository root with Python 3.11 or newer. The optimiser and tests use only the standard library.

```powershell
@'
3 7
AU 5 8 2
CN 7 20 1
US 4 3 4
'@ | python -m B.optimiser
```

```text
1 27
CN 7
```

```powershell
python -m unittest discover -s B -v
```

## Input and output conventions

- Input is UTF-8. Warehouse IDs are unique, case-sensitive, whitespace-delimited tokens ordered lexicographically as strings, so `W10` sorts before `W2`. Numerical fields use ASCII decimal digits and may have leading zeros.
- A valid order that cannot be fulfilled prints `-1`. An invalid header, row, or row count produces an error on stderr, exits with status 1, and produces no stdout. Trailing whitespace-only lines are allowed.
- A feasible result starts with the number of used warehouses and total cost, followed by each used warehouse ID and positive quantity in warehouse ID order.

## Dynamic programming

Sort the warehouses by ID. For each suffix of the sorted warehouses and each quantity from zero to `Q`, store the best pair `(warehouse count, shipping cost)` for supplying exactly that quantity. Pair comparison enforces both priorities. The empty suffix can supply zero units at zero cost. All its positive quantities are unreachable.

For quantity `r`, skipping the current warehouse copies the next suffix's score for `r`. To use the current warehouse, take the next suffix's score for `p` units and allocate the remaining `r - p` units here. If this warehouse has stock `s`, the valid values of `p` range from `max(0, r - s)` to `r - 1`. The resulting score for a next-suffix pair `(count, cost)` is given below.

```text
(count + 1, cost - p * unit_cost + fixed_cost + r * unit_cost)
```

Both `+1` and `fixed_cost + r * unit_cost` are shared across the candidates for the same `r`. A monotonic deque tracks the smallest pair `(count, cost - p * unit_cost)` in the moving window. A newer candidate with an equal or better pair can replace an older one because it expires later. Each candidate enters and leaves the deque at most once per warehouse.

## Lexicographic tie-breaking

Walk the warehouses in ID order and try positive quantities from smallest to largest. Accept the first quantity whose cost and warehouse count, plus the next suffix's optimum for the remaining units, match the current optimum. Using this warehouse makes its ID the first pair in the remaining allocation. If the warehouse can be used in an optimal allocation, this ID sorts before every later one. Among allocations starting with the same ID, the smallest feasible quantity sorts first. When no positive quantity preserves the optimum, skip the warehouse. Repeat until all units are allocated.

For example, with `Q = 4` and warehouses A, B and C each holding three units at the same rates, two warehouses are required and every two-warehouse split has the same cost. The result is `(A, 1), (B, 3)`.

## Complexity

Sorting takes `O(W log W)` ID comparisons. Filling the score table takes `O(WQ)` time. Reconstructing the allocation takes at most `O(WQ)` time because it checks at most `Q` candidate quantities per warehouse. The score table uses `O(WQ)` space, including `O(Q)` temporary space for the current transition.
