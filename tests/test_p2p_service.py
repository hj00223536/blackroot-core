import unittest
from unittest.mock import Mock

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import decode_compact_target, check_proof_of_work
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_inventory import InventoryVector, encode_inventory
from src.blackroot_p2p_service import P2PSyncService

MAGIC_BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(MAGIC_BITS)


def genesis_block():
    from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
    tx = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(1, b"miner"),),
    )
    for nonce in range(10000):
        header = BlockHeader(1, ZERO_HASH, merkle_root([tx.txid]), 1, MAGIC_BITS, nonce)
        if check_proof_of_work(header.serialize(), MAGIC_BITS, POW_LIMIT):
            return Block(header, (tx,))
    raise AssertionError("could not mine test genesis")


class FakePeer:
    connected = True

    def __init__(self):
        self.sent = []

    async def send(self, command, payload):
        self.sent.append((command, payload))


class FakeManager:
    def __init__(self, peers):
        self.peers = tuple(peers)
        self.on_peer_message_factory = None
        self.on_peer_disconnected = None


class P2PSyncServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        block = genesis_block()
        self.chain = HeaderChain(POW_LIMIT, block.header)
        self.store = Mock()
        self.store.load_block_body.return_value = None
        self.peer_a = FakePeer()
        self.peer_b = FakePeer()
        self.manager = FakeManager([self.peer_a, self.peer_b])
        self.service = P2PSyncService(
            self.manager, self.chain, self.store, protocol_version=1
        )

    async def test_notfound_is_routed_and_reassigned_through_service(self):
        block_hash = bytes.fromhex("11" * 32)
        self.service.reorg.pool.assign(block_hash, [self.peer_a])
        handler = self.manager.on_peer_message_factory(self.peer_a)
        payload = encode_inventory([InventoryVector(2, block_hash)])

        await handler("notfound", payload)

        self.assertIsNone(self.service.reorg.pool.assigned_peer(block_hash))
        self.assertEqual(len(self.peer_b.sent), 1)
        self.assertEqual(self.peer_b.sent[0][0], "getdata")

    async def test_disconnect_hook_is_installed_on_manager(self):
        self.assertIs(self.manager.on_peer_disconnected.__self__, self.service)
        self.assertEqual(self.manager.on_peer_message_factory.__self__, self.service)


if __name__ == "__main__":
    unittest.main()
