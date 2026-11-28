import tempfile
import unittest
from pathlib import Path

from src.blackroot_trust_checkpoint import TrustCheckpointStore


NETWORK = "11" * 32
DIGEST_1 = "22" * 32
DIGEST_2 = "33" * 32
DIGEST_3 = "44" * 32


class TrustCheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trust-checkpoint.sqlite"

    def test_initialize_persist_reopen_and_verify_current(self):
        with TrustCheckpointStore(self.path) as store:
            store.initialize(
                network_id=NETWORK, sequence=1, config_digest=DIGEST_1
            )
            self.assertEqual(store.current(), (NETWORK, 1, DIGEST_1, None))
        with TrustCheckpointStore(self.path) as reopened:
            reopened.verify_current(
                network_id=NETWORK, expected_sequence=1,
                expected_config_digest=DIGEST_1,
            )

    def test_initialization_is_one_time(self):
        with TrustCheckpointStore(self.path) as store:
            store.initialize(
                network_id=NETWORK, sequence=1, config_digest=DIGEST_1
            )
            with self.assertRaisesRegex(ValueError, "already initialized"):
                store.initialize(
                    network_id=NETWORK, sequence=1, config_digest=DIGEST_2
                )
            self.assertEqual(store.current()[2], DIGEST_1)

    def test_advance_requires_exact_sequence_and_predecessor(self):
        with TrustCheckpointStore(self.path) as store:
            store.initialize(
                network_id=NETWORK, sequence=1, config_digest=DIGEST_1
            )
            common = {
                "network_id": NETWORK,
                "expected_current_sequence": 1,
                "expected_current_digest": DIGEST_1,
                "new_sequence": 2,
                "new_config_digest": DIGEST_2,
                "new_previous_config_digest": DIGEST_1,
            }
            with self.assertRaisesRegex(ValueError, "exactly one"):
                store.advance(**dict(common, new_sequence=3))
            with self.assertRaisesRegex(ValueError, "predecessor"):
                store.advance(**dict(common, new_previous_config_digest=DIGEST_3))
            self.assertEqual(store.current()[1:3], (1, DIGEST_1))
            store.advance(**common)
            self.assertEqual(store.current(), (NETWORK, 2, DIGEST_2, DIGEST_1))

    def test_stale_writer_and_cross_network_are_rejected_without_mutation(self):
        with TrustCheckpointStore(self.path) as store:
            store.initialize(
                network_id=NETWORK, sequence=1, config_digest=DIGEST_1
            )
            store.advance(
                network_id=NETWORK,
                expected_current_sequence=1,
                expected_current_digest=DIGEST_1,
                new_sequence=2,
                new_config_digest=DIGEST_2,
                new_previous_config_digest=DIGEST_1,
            )
            with self.assertRaisesRegex(ValueError, "current state mismatch"):
                store.advance(
                    network_id=NETWORK,
                    expected_current_sequence=1,
                    expected_current_digest=DIGEST_1,
                    new_sequence=2,
                    new_config_digest=DIGEST_3,
                    new_previous_config_digest=DIGEST_1,
                )
            with self.assertRaisesRegex(ValueError, "network mismatch"):
                store.verify_current(
                    network_id="55" * 32,
                    expected_sequence=2,
                    expected_config_digest=DIGEST_2,
                )
            self.assertEqual(store.current()[1:3], (2, DIGEST_2))

    def test_uninitialized_and_malformed_inputs_fail_closed(self):
        with TrustCheckpointStore(self.path) as store:
            with self.assertRaisesRegex(ValueError, "not initialized"):
                store.current()
            with self.assertRaisesRegex(ValueError, "lowercase hexadecimal"):
                store.initialize(
                    network_id="AA" * 32, sequence=1, config_digest=DIGEST_1
                )
            with self.assertRaisesRegex(ValueError, "exactly 1"):
                store.initialize(
                    network_id=NETWORK, sequence=2, config_digest=DIGEST_1
                )


if __name__ == "__main__":
    unittest.main()
