import asyncio
import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, HeaderChain, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_inventory import decode_inventory, INV_TYPE_BLOCK
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_p2p_service import P2PSyncService
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root
from src.blackroot_utxo_db import UTXOStore

MAGIC = bytes.fromhex("b2a1c3d4")
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


def version(nonce):
    return VersionMessage(1, 0, 1_800_000_000, nonce, 0, "/blackroot:reorg-loopback/")


class P2PServiceReorganizationLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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
        self.blocks = {
            self.fork_one.header.hash: self.fork_one.serialize(),
            self.fork_two.header.hash: self.fork_two.serialize(),
        }
        self.served = {"source-a": asyncio.Event(), "source-b": asyncio.Event()}
        self.served_blocks = set()
        self.remote_managers = []

        def remote_factory(source_name):
            def factory(peer):
                async def handler(command, payload):
                    if command != "getdata":
                        return
                    for item in decode_inventory(payload):
                        if item.kind == INV_TYPE_BLOCK and item.item_hash in self.blocks:
                            self.served[source_name].set()
                            self.served_blocks.add(item.item_hash)
                            await peer.send("block", self.blocks[item.item_hash])
                return handler
            return factory

        for index, source_name in enumerate(("source-a", "source-b"), start=1):
            manager = PeerManager(
                magic=MAGIC,
                local_version=version(100 + index),
                max_peers=2,
                handshake_timeout=2,
                idle_timeout=5,
                on_peer_message_factory=remote_factory(source_name),
            )
            await manager.start_server("127.0.0.1", 0)
            self.remote_managers.append(manager)

        self.central = PeerManager(
            magic=MAGIC,
            local_version=version(200),
            max_peers=3,
            handshake_timeout=2,
            idle_timeout=5,
        )
        self.service = P2PSyncService(
            self.central, self.chain, self.store, protocol_version=1
        )
        self.peer_names = {}
        for source_name, manager in zip(("source-a", "source-b"), self.remote_managers):
            host, port, *_ = manager.sockets[0].getsockname()
            peer = await self.central.connect(host, port)
            self.peer_names[peer] = source_name

        async def wait_handshakes():
            while not all(peer.connected for peer in self.central.peers):
                await asyncio.sleep(0.01)
            if len(self.central.peers) != 2:
                await asyncio.sleep(0.01)
                return await wait_handshakes()
        await asyncio.wait_for(wait_handshakes(), timeout=3)

    async def asyncTearDown(self):
        await self.central.close()
        for manager in self.remote_managers:
            await manager.close()

    async def test_disconnect_reassigns_fork_bodies_to_surviving_peer(self):
        assignments = await self.service.reorg.request_missing_bodies(
            self.service._peers()
        )
        self.assertEqual(len(assignments), 2)

        disconnected_peer = assignments[self.fork_one.header.hash]
        surviving_peer = next(
            peer for peer in self.central.peers if peer is not disconnected_peer
        )
        await disconnected_peer.close()

        async def wait_for_reassignment():
            while any(
                self.service.reorg.pool.assigned_peer(block_hash) is not surviving_peer
                for block_hash in assignments
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_reassignment(), timeout=3)

        async def wait_for_reorg():
            while self.store.tip() != (2, self.fork_two.header.hash):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_reorg(), timeout=3)
        self.assertEqual(self.service.reorg.pool.pending_hashes, ())
        self.assertEqual(self.store.tip(), (2, self.fork_two.header.hash))

    async def test_tcp_rejects_overpaying_longer_fork_without_state_change(self):
        invalid_coinbase = Transaction(
            1,
            (TxInput(
                OutPoint(ZERO_TXID, COINBASE_INDEX),
                (3).to_bytes(2, "little"),
            ),),
            (TxOutput(block_subsidy(3) + 1, b"miner"),),
        )
        root = merkle_root([invalid_coinbase.txid])
        invalid_three = None
        for nonce in range(10000):
            header = BlockHeader(
                1, self.fork_two.header.hash, root, 5, BITS, nonce
            )
            if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
                invalid_three = Block(header, (invalid_coinbase,))
                break
        self.assertIsNotNone(invalid_three)
        self.chain.add_to_branch(invalid_three.header)
        self.blocks[invalid_three.header.hash] = invalid_three.serialize()

        original_tip = self.store.tip()
        with self.store._connection_scope() as db:
            original_utxos = db.execute(
                "SELECT txid, output_index, value, script_pubkey, created_height, "
                "is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index"
            ).fetchall()
        assignments = await self.service.reorg.request_missing_bodies(
            self.service._peers()
        )
        expected = {
            self.fork_one.header.hash,
            self.fork_two.header.hash,
            invalid_three.header.hash,
        }
        self.assertEqual(set(assignments), expected)

        async def wait_for_invalid_branch_rejection():
            # The final body is validated and rejected synchronously by
            # accept_block(), which also removes every body in the candidate
            # branch before returning. Therefore, observing all bodies archived
            # at once is impossible for this invalid-fork case. Instead prove
            # every body was served over TCP, then wait for assignment release
            # and rejection cleanup to finish.
            while not expected.issubset(self.served_blocks):
                await asyncio.sleep(0.01)
            while self.service.reorg.pool.pending_hashes or any(
                self.store.load_block_body(block_hash) is not None
                for block_hash in expected
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_invalid_branch_rejection(), timeout=5)
        self.assertEqual(self.store.tip(), original_tip)
        for block_hash in expected:
            self.assertIsNone(self.store.load_block_body(block_hash))
        with self.store._connection_scope() as db:
            restored_utxos = db.execute(
                "SELECT txid, output_index, value, script_pubkey, created_height, "
                "is_coinbase, created_mtp FROM utxos ORDER BY txid, output_index"
            ).fetchall()
        self.assertEqual(restored_utxos, original_utxos)
        self.store.verify_integrity()

    async def test_service_downloads_fork_bodies_over_tcp_and_reorganizes(self):
        assignments = await self.service.reorg.request_missing_bodies(
            self.service._peers()
        )
        self.assertEqual(
            set(assignments),
            {self.fork_one.header.hash, self.fork_two.header.hash},
        )
        self.assertEqual(len(set(assignments.values())), 2)

        async def wait_for_reorg():
            while self.store.tip() != (2, self.fork_two.header.hash):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_reorg(), timeout=3)
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in self.served.values())),
            timeout=3,
        )
        self.assertEqual(self.store.tip(), (2, self.fork_two.header.hash))
        self.assertEqual(self.service.reorg.pool.pending_hashes, ())
        self.assertEqual(self.service.reorg._requested_at, {})


if __name__ == "__main__":
    unittest.main()
