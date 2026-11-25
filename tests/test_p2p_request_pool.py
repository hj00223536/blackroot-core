import unittest

from src.blackroot_p2p_request_pool import MultiPeerBlockRequestPool


class MultiPeerBlockRequestPoolTests(unittest.TestCase):
    def setUp(self):
        self.pool = MultiPeerBlockRequestPool(max_total=4, max_per_peer=2)

    def test_distributes_requests_across_least_loaded_peers(self):
        first = self.pool.assign(b"a" * 32, ["peer-a", "peer-b"])
        second = self.pool.assign(b"b" * 32, ["peer-a", "peer-b"])
        self.assertEqual(first, "peer-a")
        self.assertEqual(second, "peer-b")
        self.assertEqual(self.pool.peer_load("peer-a"), 1)
        self.assertEqual(self.pool.peer_load("peer-b"), 1)

    def test_respects_per_peer_limit_and_uses_alternative(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        self.pool.assign(b"b" * 32, ["peer-a"])
        chosen = self.pool.assign(b"c" * 32, ["peer-a", "peer-b"])
        self.assertEqual(chosen, "peer-b")

    def test_rejects_when_all_peers_are_at_capacity(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        self.pool.assign(b"b" * 32, ["peer-a"])
        with self.assertRaisesRegex(ValueError, "request limit"):
            self.pool.assign(b"c" * 32, ["peer-a"])

    def test_rejects_duplicate_and_global_overflow(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        with self.assertRaisesRegex(ValueError, "already has"):
            self.pool.assign(b"a" * 32, ["peer-b"])
        self.pool.assign(b"b" * 32, ["peer-b"])
        self.pool.assign(b"c" * 32, ["peer-c"])
        self.pool.assign(b"d" * 32, ["peer-d"])
        with self.assertRaisesRegex(ValueError, "global"):
            self.pool.assign(b"e" * 32, ["peer-e"])

    def test_only_assigned_peer_can_complete_request(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        self.assertFalse(self.pool.complete(b"a" * 32, "peer-b"))
        self.assertEqual(self.pool.assigned_peer(b"a" * 32), "peer-a")
        self.assertTrue(self.pool.complete(b"a" * 32, "peer-a"))
        self.assertFalse(self.pool.complete(b"a" * 32, "peer-a"))

    def test_disconnect_releases_all_peer_assignments(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        self.pool.assign(b"b" * 32, ["peer-a"])
        self.pool.assign(b"c" * 32, ["peer-b"])
        released = self.pool.release_peer("peer-a")
        self.assertEqual(set(released), {b"a" * 32, b"b" * 32})
        self.assertEqual(self.pool.pending_hashes, (b"c" * 32,))
        self.assertEqual(self.pool.peer_load("peer-a"), 0)

    def test_cancel_releases_assignment(self):
        self.pool.assign(b"a" * 32, ["peer-a"])
        self.assertTrue(self.pool.cancel(b"a" * 32))
        self.assertFalse(self.pool.cancel(b"a" * 32))
        self.assertEqual(self.pool.peer_load("peer-a"), 0)

    def test_validates_limits_and_hash(self):
        with self.assertRaises(ValueError):
            MultiPeerBlockRequestPool(max_total=2, max_per_peer=3)
        with self.assertRaises(ValueError):
            self.pool.assign(b"short", ["peer-a"])
        with self.assertRaises(ValueError):
            self.pool.assign(b"x" * 32, [])


if __name__ == "__main__":
    unittest.main()
