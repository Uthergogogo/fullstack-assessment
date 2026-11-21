from io import BytesIO, StringIO
import unittest

from A.ledger import run


def run_batch(data: bytes) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    status = run(BytesIO(data), stdout, stderr)
    return status, stdout.getvalue(), stderr.getvalue()


class LedgerTests(unittest.TestCase):
    def assert_batch_output(self, data: bytes, *expected_lines: str) -> None:
        self.assertEqual(run_batch(data), (0, "\n".join(expected_lines) + "\n", ""))

    def test_assessment_example(self) -> None:
        self.assert_batch_output(
            b"10 6\n"
            b"RESERVE e1 o100 4\n"
            b"RESERVE e2 o200 7\n"
            b"SHIP e3 o100 2\n"
            b"RELEASE e4 o100 2\n"
            b"RESTOCK e5 3\n"
            b"RESERVE e2 o999 1\n",
            "OK 10 4",
            "REJECTED 10 4",
            "OK 8 2",
            "OK 8 0",
            "OK 11 0",
            "DUPLICATE 11 0",
            "OPEN 0",
        )

    def test_replay_after_restock_does_not_turn_rejection_into_success(self) -> None:
        self.assert_batch_output(
            b"0 5\n"
            b"RESERVE denied order 1\n"
            b"RESTOCK refill 3\n"
            b"RESERVE denied order 1\n"
            b"SHIP refill order 1\n"
            b"RESERVE new order 1\n",
            "REJECTED 0 0",
            "OK 3 0",
            "DUPLICATE 3 0",
            "DUPLICATE 3 0",
            "OK 3 1",
            "OPEN 1",
            "order 1",
        )

    def test_release_and_ship_cannot_use_another_orders_reservation(self) -> None:
        self.assert_batch_output(
            b"5 9\n"
            b"RESERVE e1 order 2\n"
            b"RESERVE e2 order 1\n"
            b"RESERVE e8 other 2\n"
            b"RELEASE e3 missing 1\n"
            b"SHIP e4 order 4\n"
            b"RELEASE e5 order 2\n"
            b"SHIP e6 order 1\n"
            b"RELEASE e7 order 1\n"
            b"RELEASE e3 order 1\n",
            "OK 5 2",
            "OK 5 3",
            "OK 5 5",
            "REJECTED 5 5",
            "REJECTED 5 5",
            "OK 5 3",
            "OK 4 2",
            "REJECTED 4 2",
            "DUPLICATE 4 2",
            "OPEN 1",
            "other 2",
        )

    def test_open_orders_are_sorted_by_case_sensitive_id(self) -> None:
        self.assert_batch_output(
            b"5 5\r\n"
            b"RESERVE e1 o2 1\r\n"
            b"RESERVE e2 o10 2\r\n"
            b"RESERVE\te3\tO2\t1\r\n"
            b"SHIP e4 o10 1\r\n"
            b"RESERVE e5 o2 1",
            "OK 5 1",
            "OK 5 3",
            "OK 5 4",
            "OK 4 3",
            "OK 4 4",
            "OPEN 3",
            "O2 1",
            "o10 1",
            "o2 2",
        )

    def test_malformed_commands_do_not_mutate_stock_or_consume_event_id(self) -> None:
        malformed = (
            b"",
            b"restock repair 1",
            b"RESTOCK repair 1 extra",
            b"RESERVE repair 1",
            b"RESERVE repair order 0",
            b"RESERVE repair order -1",
            b"RESERVE repair order +1",
            b"RESERVE repair order 1_0",
            b"RESERVE repair order 1000000000001",
            b"RESTOCK repair " + b"9" * 5000,
            b"RESERVE repair \xff 1",
            b"RESTOCK rep\xffair 1",
        )
        for line in malformed:
            with self.subTest(line=line[:80]):
                self.assert_batch_output(
                    b"1 3\nRESERVE held order 1\n" + line + b"\nRESTOCK repair 2\n",
                    "OK 1 1",
                    "REJECTED 1 1",
                    "OK 3 1",
                    "OPEN 1",
                    "order 1",
                )

    def test_malformed_replay_is_validated_before_duplicate_check(self) -> None:
        self.assert_batch_output(
            b"1 3\nRESTOCK event 1\nRESTOCK event 0\nRESTOCK event 2\n",
            "OK 2 0",
            "REJECTED 2 0",
            "DUPLICATE 2 0",
            "OPEN 0",
        )

    def test_limits_apply_to_inputs_not_to_cumulative_stock(self) -> None:
        self.assert_batch_output(
            b"1000000000000 3\n"
            b"RESTOCK e1 1000000000000\n"
            b"RESERVE e2 order 0000001000000000000\n"
            b"SHIP e3 order 1000000000000\n\n \t\n",
            "OK 2000000000000 0",
            "OK 2000000000000 1000000000000",
            "OK 1000000000000 0",
            "OPEN 0",
        )

    def test_invalid_batch_shape_has_no_stdout(self) -> None:
        invalid_batches = (
            b"",
            b"10\n",
            b"10 1 extra\nRESTOCK e1 1\n",
            b"-1 1\nRESTOCK e1 1\n",
            b"1000000000001 1\nRESTOCK e1 1\n",
            b"10 0\n",
            b"10 200001\n",
            b"10 2\nRESERVE e1 order 1\n",
            b"10 1\nRESERVE e1 order 1\n\nRESTOCK e2 1\n",
        )
        for data in invalid_batches:
            with self.subTest(data=data):
                status, stdout, stderr = run_batch(data)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("Input error: "), stderr)
