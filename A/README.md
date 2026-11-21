# Task A — Inventory Reservation Ledger

Run from the repository root with Python 3.11 or newer. The program and tests use only the standard library.

```powershell
@'
0 4
RESERVE e1 order1 1
RESTOCK e2 2
RESERVE e1 order1 1
RESERVE e3 order1 1
'@ | python -m A.ledger
```

```text
REJECTED 0 0
OK 2 0
DUPLICATE 2 0
OK 2 1
OPEN 1
order1 1
```

```powershell
python -m unittest discover -s A -v
```

## Input and output conventions

- The header declares initial stock and the number of command lines. A blank line within that count is a malformed command. Trailing whitespace-only lines are allowed. An invalid header or a command-count mismatch writes an error to stderr, exits with status 1, and produces no stdout.
- Commands are uppercase and fields are separated by ASCII whitespace. Integers use ASCII decimal digits and may have leading zeros. IDs are case-sensitive ASCII tokens.
- Commands are validated before the duplicate check. A malformed command reports `REJECTED` with the current totals and leaves its event ID available. A valid command claims its event ID even when the inventory rules reject it. Any later valid command with that ID reports `DUPLICATE` with the current totals, even if its action or arguments differ.
- The footer is `OPEN k`, followed by `k` lines of `order_id qty` for positive reservations in ascending ASCII order.

## State and complexity

The ledger stores on-hand stock, the total reserved, a dictionary of positive reservations by order ID, and a set of processed event IDs. The total reserved equals the sum of the order reservations and stays between zero and on-hand stock. `RELEASE` frees a reservation. `SHIP` reduces on-hand stock and the reservation by the same amount, so available stock (`on_hand - reserved`) stays the same.

Command processing takes expected `O(N)` dictionary and set operations, plus the cost of reading and parsing the input. Sorting the `k` open orders takes `O(k log k)` ID comparisons. The ledger holds `O(N)` entries. The CLI also buffers the input command lines so it can validate the batch size before processing.
