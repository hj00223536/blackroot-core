import ipaddress
import unittest

from src.blackroot_p2p_addr import PeerAddress
from src.blackroot_p2p_address_book import PeerAddressBook, is_eligible_address


def address(ip, port=8333, timestamp=1_800_000_000):
    return PeerAddress(timestamp, 1, ipaddress.ip_address(ip), port)


class PeerAddressBookTests(unittest.TestCase):
    def setUp(self):
        self.book = PeerAddressBook(
            max_entries=2, max_age_seconds=100, future_skew_seconds=10,
            clock=lambda: 1_800_000_000,
        )

    def test_accepts_global_unicast_and_deduplicates(self):
        first = address("8.8.8.8")
        self.assertTrue(self.book.add(first, source="seed", now=1_800_000_000))
        refreshed = address("8.8.8.8", timestamp=1_800_000_001)
        self.assertTrue(self.book.add(refreshed, source="peer-a", now=1_800_000_001))
        self.assertEqual(len(self.book), 1)
        self.assertEqual(self.book.entries[0].source, "peer-a")

    def test_rejects_private_loopback_link_local_and_documentation_ranges(self):
        for ip in ("10.0.0.1", "127.0.0.1", "169.254.1.1", "192.0.2.1", "::1", "2001:db8::1"):
            self.assertFalse(is_eligible_address(address(ip)))
            self.assertFalse(self.book.add(address(ip), source="untrusted", now=1_800_000_000))
        self.assertEqual(len(self.book), 0)

    def test_rejects_stale_and_future_timestamps(self):
        self.assertFalse(self.book.add(address("8.8.4.4", timestamp=1_799_999_899), source="peer", now=1_800_000_000))
        self.assertFalse(self.book.add(address("1.1.1.1", timestamp=1_800_000_011), source="peer", now=1_800_000_000))

    def test_capacity_and_pruning(self):
        self.assertTrue(self.book.add(address("8.8.8.8"), source="a", now=1_800_000_000))
        self.assertTrue(self.book.add(address("1.1.1.1"), source="b", now=1_800_000_000))
        self.assertFalse(self.book.add(address("9.9.9.9"), source="c", now=1_800_000_000))
        self.assertEqual(self.book.prune(now=1_800_000_101), 2)
        self.assertEqual(len(self.book), 0)
        self.assertTrue(self.book.add(address("9.9.9.9"), source="c", now=1_800_000_000))

    def test_rejects_older_duplicate_and_invalid_source(self):
        self.book.add(address("8.8.8.8", timestamp=1_800_000_001), source="peer", now=1_800_000_001)
        self.assertFalse(self.book.add(address("8.8.8.8"), source="older", now=1_800_000_001))
        with self.assertRaises(ValueError):
            self.book.add(address("1.1.1.1"), source="", now=1_800_000_000)


if __name__ == "__main__":
    unittest.main()
