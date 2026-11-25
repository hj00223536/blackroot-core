import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_inventory import (
    INV_TYPE_BLOCK, InventoryVector, encode_inventory, decode_inventory,
)
from src.blackroot_p2p_multi_peer_sync import MultiPeerBlockScheduler
from src.blackroot_p2p_node_service import NodePeerSyncService

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def make_block():
    from src.blackroot_transactions import (
        OutPoint, Transaction, TxInput, TxOutput, merkle_root,
    )
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


class NodePeerSyncServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.block = make_block()
        self.chain = HeaderChain(POW_LIMIT, self.block.header)
        self.store = Mock()
        self.store.connect_validated_block.return_value = 0
        self.scheduler = MultiPeerBlockScheduler(self.chain, self.store)
        self.service = NodePeerSyncService(self.scheduler)
        self.a, self.b = FakePeer(), FakePeer()
        self.service.register_peer("a", self.a)
        self.service.register_peer("b", self.b)

    async def test_inventory_routes_request_and_block_to_assigned_peer(self):
        payload = encode_inventory([
            InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        ])
        await self.service.handle_message("a", self.a, "inv", payload)
        assigned = self.scheduler.pool.assigned_peer(self.block.header.hash)
        self.assertIn(assigned, ("a", "b"))
        selected = self.a if assigned == "a" else self.b
        self.assertEqual(decode_inventory(selected.sent[0][1])[0].item_hash,
                         self.block.header.hash)
        await self.service.handle_message(
            assigned, selected, "block", self.block.serialize()
        )
        self.store.connect_validated_block.assert_called_once()
        self.assertEqual(self.scheduler.pool.pending_hashes, ())

    async def test_notfound_reassigns_to_other_peer(self):
        payload = encode_inventory([
            InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        ])
        await self.service.handle_message("a", self.a, "inv", payload)
        first = self.scheduler.pool.assigned_peer(self.block.header.hash)
        first_peer = self.a if first == "a" else self.b
        other_id = "b" if first == "a" else "a"
        other_peer = self.b if other_id == "b" else self.a
        await self.service.handle_message(
            first, first_peer, "notfound", payload
        )
        self.assertEqual(self.scheduler.pool.assigned_peer(self.block.header.hash),
                         other_id)
        self.assertEqual(len(other_peer.sent), 1)

    async def test_disconnect_reassigns_pending_requests(self):
        payload = encode_inventory([
            InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        ])
        await self.service.handle_message("a", self.a, "inv", payload)
        first = self.scheduler.pool.assigned_peer(self.block.header.hash)
        disconnected = self.a if first == "a" else self.b
        survivor_id = "b" if first == "a" else "a"
        await self.service.peer_disconnected(first)
        self.assertEqual(self.scheduler.pool.assigned_peer(self.block.header.hash),
                         survivor_id)
        self.assertNotIn(first, self.service.peers)

    async def test_unassigned_notfound_does_not_cancel_another_peer_request(self):
        payload = encode_inventory([
            InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        ])
        await self.service.handle_message("a", self.a, "inv", payload)
        assigned = self.scheduler.pool.assigned_peer(self.block.header.hash)
        stranger = "b" if assigned == "a" else "a"
        stranger_peer = self.b if stranger == "b" else self.a
        await self.service.handle_message(stranger, stranger_peer, "notfound", payload)
        self.assertEqual(self.scheduler.pool.assigned_peer(self.block.header.hash),
                         assigned)


if __name__ == "__main__":
    unittest.main()
