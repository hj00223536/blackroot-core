import unittest

from src.blackroot_p2p_resources import ResourceBudget, reserve_resources


class ResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.peer = ResourceBudget(max_items=3, max_bytes=100, name="peer")
        self.node = ResourceBudget(max_items=5, max_bytes=150, name="node")

    def test_atomic_reservation_charges_peer_and_node(self):
        reservation = reserve_resources(((self.peer, 1, 40), (self.node, 1, 40)))
        self.assertIsNotNone(reservation)
        self.assertEqual((self.peer.items_in_use, self.peer.bytes_in_use), (1, 40))
        self.assertEqual((self.node.items_in_use, self.node.bytes_in_use), (1, 40))
        reservation.release()
        self.assertEqual((self.peer.items_in_use, self.peer.bytes_in_use), (0, 0))
        self.assertEqual((self.node.items_in_use, self.node.bytes_in_use), (0, 0))

    def test_failed_second_budget_does_not_charge_first(self):
        blocker = reserve_resources(((self.node, 5, 150),))
        self.assertIsNotNone(blocker)
        rejected = reserve_resources(((self.peer, 1, 10), (self.node, 1, 1)))
        self.assertIsNone(rejected)
        self.assertEqual((self.peer.items_in_use, self.peer.bytes_in_use), (0, 0))
        blocker.release()

    def test_count_and_byte_limits_are_both_enforced(self):
        held = reserve_resources(((self.peer, 3, 100),))
        self.assertIsNotNone(held)
        self.assertFalse(self.peer.can_reserve(items=1, byte_count=0))
        self.assertFalse(self.peer.can_reserve(items=1, byte_count=1))
        held.release()

    def test_release_is_exactly_once(self):
        reservation = reserve_resources(((self.peer, 2, 20),))
        reservation.release()
        with self.assertRaisesRegex(RuntimeError, "more than once"):
            reservation.release()

    def test_context_manager_releases_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, "expected"):
            with reserve_resources(((self.peer, 1, 12),)):
                raise RuntimeError("expected")
        self.assertEqual((self.peer.items_in_use, self.peer.bytes_in_use), (0, 0))

    def test_rejects_invalid_limits_and_requests(self):
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ResourceBudget(max_items=value, max_bytes=10, name="bad")
        with self.assertRaises(ValueError):
            self.peer.can_reserve(items=True)
        with self.assertRaises(ValueError):
            self.peer.can_reserve(byte_count=-1)
        with self.assertRaises(ValueError):
            reserve_resources(((self.peer, 1, 1), (self.peer, 1, 1)))


if __name__ == "__main__":
    unittest.main()
