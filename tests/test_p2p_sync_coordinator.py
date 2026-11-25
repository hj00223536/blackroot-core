import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_getheaders import decode_getheaders
from src.blackroot_p2p_header_sync import PeerHeaderSync
from src.blackroot_p2p_inventory import INV_TYPE_BLOCK, InventoryVector, decode_inventory, encode_inventory
from src.blackroot_p2p_sync_coordinator import PeerSyncCoordinator
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def mine(previous, timestamp, root):
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return header
    raise AssertionError("nonce search exhausted")


def make_block(previous=ZERO_HASH, timestamp=1):
    coinbase = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(1, b"miner"),),
    )
    header = mine(previous, timestamp, merkle_root([coinbase.txid]))
    return Block(header, (coinbase,))


class FakePeer:
    connected = True

    def __init__(self):
        self.sent = []

    async def send(self, command, payload):
        self.sent.append((command, payload))


class PeerSyncCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.block = make_block()
        self.chain = HeaderChain(POW_LIMIT, self.block.header)
        self.header_sync = PeerHeaderSync(self.chain, protocol_version=70001)
        self.store = Mock()
        self.store.connect_validated_block.return_value = 0
        self.peer = FakePeer()
        self.coordinator = PeerSyncCoordinator(
            self.header_sync, block_provider=lambda block_hash: (
                self.block.serialize() if block_hash == self.block.header.hash else None
            )
        )
        self.coordinator.attach_store(self.store)

    async def test_unknown_inventory_requests_headers_once(self):
        unknown = InventoryVector(INV_TYPE_BLOCK, b"u" * 32)
        payload = encode_inventory([unknown])
        await self.coordinator.handle_message(self.peer, "inv", payload)
        await self.coordinator.handle_message(self.peer, "inv", payload)
        self.assertEqual([command for command, _ in self.peer.sent], ["getheaders"])
        self.assertEqual(decode_getheaders(self.peer.sent[0][1]).locator_hashes[0], self.block.header.hash)

    async def test_known_best_chain_inventory_requests_body(self):
        item = InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        await self.coordinator.handle_message(self.peer, "inv", encode_inventory([item]))
        command, payload = self.peer.sent[0]
        self.assertEqual(command, "getdata")
        self.assertEqual(decode_inventory(payload), [item])
        self.assertEqual(self.coordinator.requests.pending_hashes, (self.block.header.hash,))

    async def test_duplicate_inventory_does_not_duplicate_getdata(self):
        item = InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        payload = encode_inventory([item])
        await self.coordinator.handle_message(self.peer, "inv", payload)
        await self.coordinator.handle_message(self.peer, "inv", payload)
        self.assertEqual(len(self.peer.sent), 1)

    async def test_requested_block_is_connected(self):
        item = InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        await self.coordinator.handle_message(self.peer, "inv", encode_inventory([item]))
        await self.coordinator.handle_message(self.peer, "block", self.block.serialize())
        self.store.connect_validated_block.assert_called_once()
        self.assertEqual(self.coordinator.requests.pending_hashes, ())

    async def test_unsolicited_block_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsolicited"):
            await self.coordinator.handle_message(self.peer, "block", self.block.serialize())
        self.store.connect_validated_block.assert_not_called()

    async def test_serves_requested_body_and_reports_missing(self):
        item = InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        missing = InventoryVector(INV_TYPE_BLOCK, b"m" * 32)
        await self.coordinator.handle_message(
            self.peer, "getdata", encode_inventory([item, missing])
        )
        self.assertEqual([command for command, _ in self.peer.sent], ["block", "notfound"])
        self.assertEqual(self.peer.sent[0][1], self.block.serialize())
        self.assertEqual(decode_inventory(self.peer.sent[1][1]), [missing])

    async def test_notfound_cancels_outstanding_request(self):
        item = InventoryVector(INV_TYPE_BLOCK, self.block.header.hash)
        await self.coordinator.handle_message(self.peer, "inv", encode_inventory([item]))
        await self.coordinator.handle_message(self.peer, "notfound", encode_inventory([item]))
        self.assertEqual(self.coordinator.requests.pending_hashes, ())

    async def test_rejects_messages_before_handshake(self):
        self.peer.connected = False
        with self.assertRaisesRegex(ConnectionError, "handshake"):
            await self.coordinator.handle_message(self.peer, "inv", encode_inventory([]))


if __name__ == "__main__":
    unittest.main()
