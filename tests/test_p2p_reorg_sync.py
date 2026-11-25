import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_p2p_inventory import InventoryVector, decode_inventory, encode_inventory
from src.blackroot_p2p_reorg_sync import MultiPeerReorganizationSync
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)


def coinbase(height):
    return Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), height.to_bytes(2, "little")),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )


def mined_block(height, previous, timestamp):
    txs = (coinbase(height),)
    root = merkle_root([tx.txid for tx in txs])
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, txs)
    raise AssertionError("nonce search exhausted")


class FakePeer:
    connected = True

    def __init__(self):
        self.sent = []

    async def send(self, command, payload):
        self.sent.append((command, payload))


class MultiPeerReorganizationSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UTXOStore(Path(self.temp.name) / "chain.sqlite")
        self.genesis = mined_block(0, ZERO_HASH, 1)
        self.chain = HeaderChain(POW_LIMIT, self.genesis.header)
        self.old = mined_block(1, self.genesis.header.hash, 2)
        self.chain.add(self.old.header)
        self.store.connect_validated_block(self.genesis, 0, self.chain)
        self.store.connect_validated_block(self.old, 1, self.chain)
        self.fork_one = mined_block(1, self.genesis.header.hash, 3)
        self.chain.add_to_branch(self.fork_one.header)
        self.fork_two = mined_block(2, self.fork_one.header.hash, 4)
        self.chain.add_to_branch(self.fork_two.header)
        self.sync = MultiPeerReorganizationSync(self.chain, self.store)
        self.peers = {"p1": FakePeer(), "p2": FakePeer()}

    async def test_downloads_all_fork_bodies_then_atomically_reorganizes(self):
        missing = self.sync.missing_best_branch_bodies()
        self.assertEqual(missing, (self.fork_one.header.hash, self.fork_two.header.hash))
        assignments = await self.sync.request_missing_bodies(self.peers)
        self.assertEqual(set(assignments), set(missing))
        self.assertNotEqual(assignments[missing[0]], assignments[missing[1]])
        for block_hash, peer_id in assignments.items():
            sent = self.peers[peer_id].sent
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0], "getdata")
            self.assertEqual(decode_inventory(sent[0][1])[0].item_hash, block_hash)

        first_hash, second_hash = missing
        first_block = self.fork_one if first_hash == self.fork_one.header.hash else self.fork_two
        second_block = self.fork_two if first_block is self.fork_one else self.fork_one
        first_result = self.sync.accept_block(assignments[first_hash], first_block.serialize())
        self.assertIsNone(first_result)
        second_result = self.sync.accept_block(assignments[second_hash], second_block.serialize())
        self.assertEqual(second_result, (2, self.fork_two.header.hash))
        self.assertEqual(self.store.tip(), second_result)
        self.assertEqual(self.sync.pool.pending_hashes, ())

    async def test_unassigned_peer_cannot_supply_fork_body(self):
        assignments = await self.sync.request_missing_bodies(self.peers)
        block = self.fork_one
        assigned = assignments[block.header.hash]
        with self.assertRaisesRegex(ValueError, "unassigned peer"):
            self.sync.accept_block("attacker", block.serialize())
        self.assertEqual(self.sync.pool.assigned_peer(block.header.hash), assigned)

    async def test_invalid_merkle_body_is_rejected_and_request_slot_released(self):
        assignments = await self.sync.request_missing_bodies(self.peers)
        block_hash = self.fork_one.header.hash
        assigned_peer = assignments[block_hash]
        invalid_body = Block(self.fork_one.header, (coinbase(99),))
        original_tip = self.store.tip()

        with self.assertRaisesRegex(ValueError, "Merkle root mismatch"):
            self.sync.accept_block(assigned_peer, invalid_body.serialize())

        self.assertIsNone(self.store.load_block_body(block_hash))
        self.assertEqual(self.store.tip(), original_tip)
        self.assertIsNone(self.sync.pool.assigned_peer(block_hash))
        self.assertNotIn(block_hash, self.sync.pool.pending_hashes)
        self.assertNotIn(block_hash, self.sync._requested_at)

    async def test_expired_request_is_reassigned_to_another_connected_peer(self):
        import time

        assignments = await self.sync.request_missing_bodies(self.peers)
        block_hash = self.fork_one.header.hash
        original_peer = assignments[block_hash]
        self.peers[original_peer].connected = False
        retried = await self.sync.retry_expired_requests(
            self.peers, timeout=5, now=time.monotonic() + 10
        )
        self.assertEqual(retried[block_hash], "p2" if original_peer == "p1" else "p1")
        self.assertEqual(self.sync.pool.assigned_peer(block_hash), retried[block_hash])
        self.assertEqual(self.peers[retried[block_hash]].sent[-1][0], "getdata")

    async def test_expire_requests_rejects_nonpositive_timeout(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            self.sync.expire_requests(0)

    async def test_notfound_from_assigned_peer_releases_and_retries_body(self):
        assignments = await self.sync.request_missing_bodies(self.peers)
        block_hash = self.fork_one.header.hash
        original_peer = assignments[block_hash]
        other_peer = "p2" if original_peer == "p1" else "p1"
        payload = encode_inventory([InventoryVector(2, block_hash)])

        self.assertEqual(self.sync.peer_notfound("unassigned", payload), ())
        self.assertEqual(self.sync.pool.assigned_peer(block_hash), original_peer)
        released = self.sync.peer_notfound(original_peer, payload)
        self.assertEqual(released, (block_hash,))
        self.peers[original_peer].connected = False

        retried = await self.sync.retry_released_bodies(released, self.peers)
        self.assertEqual(retried, {block_hash: other_peer})
        self.assertEqual(self.sync.pool.assigned_peer(block_hash), other_peer)

    async def test_disconnect_releases_fork_requests(self):
        assignments = await self.sync.request_missing_bodies(self.peers)
        peer_id = next(iter(assignments.values()))
        released = self.sync.peer_disconnected(peer_id)
        self.assertTrue(released)
        self.assertTrue(all(self.sync.pool.assigned_peer(h) is None for h in released))


if __name__ == "__main__":
    unittest.main()
