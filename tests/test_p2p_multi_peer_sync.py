import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_multi_peer_sync import MultiPeerBlockScheduler
from src.blackroot_p2p_inventory import decode_inventory

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def make_block():
    from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
    coinbase = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(1, b"miner"),),
    )
    for nonce in range(10000):
        header = BlockHeader(1, ZERO_HASH, merkle_root([coinbase.txid]), 1, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, (coinbase,))
    raise AssertionError("nonce search exhausted")


class FakePeer:
    connected = True

    def __init__(self):
        self.sent = []

    async def send(self, command, payload):
        self.sent.append((command, payload))


class MultiPeerBlockSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.block = make_block()
        self.chain = HeaderChain(POW_LIMIT, self.block.header)
        self.store = Mock()
        self.store.connect_validated_block.return_value = 0
        self.scheduler = MultiPeerBlockScheduler(self.chain, self.store)
        self.peer_a = FakePeer()
        self.peer_b = FakePeer()
        self.peers = {"a": self.peer_a, "b": self.peer_b}

    async def test_request_is_sent_to_selected_peer_and_response_validated(self):
        chosen = await self.scheduler.request_block(self.block.header.hash, self.peers)
        selected = self.peers[chosen]
        other = self.peer_b if selected is self.peer_a else self.peer_a
        self.assertEqual(len(selected.sent), 1)
        self.assertEqual(selected.sent[0][0], "getdata")
        self.assertEqual(decode_inventory(selected.sent[0][1])[0].item_hash, self.block.header.hash)
        with self.assertRaisesRegex(ValueError, "unassigned peer"):
            self.scheduler.accept_block("not-" + chosen, self.block.serialize())
        self.assertEqual(self.scheduler.tracker.pending_hashes, (self.block.header.hash,))
        self.assertEqual(self.scheduler.pool.assigned_peer(self.block.header.hash), chosen)
        self.store.connect_validated_block.assert_not_called()
        result = self.scheduler.accept_block(chosen, self.block.serialize())
        self.assertEqual(result, (0, 0))
        self.store.connect_validated_block.assert_called_once()
        self.assertEqual(self.scheduler.pool.pending_hashes, ())

    async def test_disconnect_releases_requests_for_retry(self):
        chosen = await self.scheduler.request_block(self.block.header.hash, self.peers)
        released = self.scheduler.peer_disconnected(chosen)
        self.assertEqual(released, (self.block.header.hash,))
        self.assertEqual(self.scheduler.pool.pending_hashes, ())
        self.assertEqual(self.scheduler.tracker.pending_hashes, ())

    async def test_rejects_when_no_peer_is_connected(self):
        self.peer_a.connected = False
        self.peer_b.connected = False
        with self.assertRaisesRegex(ValueError, "no eligible peers"):
            await self.scheduler.request_block(self.block.header.hash, self.peers)

    async def test_send_failure_rolls_back_assignment_and_tracker(self):
        class BrokenPeer(FakePeer):
            async def send(self, command, payload):
                raise OSError("simulated disconnect")
        with self.assertRaises(OSError):
            await self.scheduler.request_block(
                self.block.header.hash, {"broken": BrokenPeer()}
            )
        self.assertEqual(self.scheduler.pool.pending_hashes, ())
        self.assertEqual(self.scheduler.tracker.pending_hashes, ())


if __name__ == "__main__":
    unittest.main()
