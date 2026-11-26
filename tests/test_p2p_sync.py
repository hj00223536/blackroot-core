import unittest

from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target
from src.blackroot_p2p_headers import encode_headers
from src.blackroot_p2p_sync import accept_headers_payload

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(previous, timestamp, *, nonce_start=0):
    from src.blackroot_consensus import check_proof_of_work
    for nonce in range(nonce_start, nonce_start + 1000):
        candidate = BlockHeader(1, previous, bytes([timestamp % 256]) * 32, timestamp, BITS, nonce)
        if check_proof_of_work(candidate.serialize(), BITS, POW_LIMIT):
            return candidate
    raise AssertionError("nonce search exhausted")


class P2PHeaderAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.genesis = mine(ZERO_HASH, 1)
        self.chain = HeaderChain(POW_LIMIT, self.genesis, adjusted_time_provider=lambda: 1_000_000)

    def test_accepts_valid_contiguous_batch(self):
        first = mine(self.genesis.hash, 2)
        second = mine(first.hash, 3)
        result = accept_headers_payload(self.chain, encode_headers([first, second]))
        self.assertEqual(result, [first.display_hash, second.display_hash])
        self.assertEqual(self.chain.height, 2)
        self.assertEqual(self.chain.tip.hash, second.hash)

    def test_rejects_invalid_batch_without_partial_chain_mutation(self):
        valid = mine(self.genesis.hash, 2)
        invalid = mine(valid.hash, 1)
        before_hashes = tuple(node.header.hash for node in self.chain.nodes)
        before_tip = self.chain.best_hash
        with self.assertRaisesRegex(ValueError, "median-time-past"):
            accept_headers_payload(self.chain, encode_headers([valid, invalid]))
        self.assertEqual(tuple(node.header.hash for node in self.chain.nodes), before_hashes)
        self.assertEqual(self.chain.best_hash, before_tip)

    def test_rejects_unknown_parent(self):
        unknown = mine(bytes.fromhex("77" * 32), 2)
        with self.assertRaisesRegex(ValueError, "unknown parent"):
            accept_headers_payload(self.chain, encode_headers([unknown]))
        self.assertEqual(self.chain.height, 0)

    def test_empty_headers_is_noop(self):
        self.assertEqual(accept_headers_payload(self.chain, encode_headers([])), [])
        self.assertEqual(self.chain.height, 0)


if __name__ == "__main__":
    unittest.main()
