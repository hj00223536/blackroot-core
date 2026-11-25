"""Real TCP loopback integration for header plus requested block-body sync.

This verifies the current experimental transport path with independent node
state, real PeerManager sockets, and a real persistent UTXO store. It is not a
production-consensus or public-network readiness test.
"""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import block_subsidy, check_proof_of_work, decode_compact_target
from src.blackroot_node_runtime import BlackrootNodeRuntime
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_header_sync import PeerHeaderSync
from src.blackroot_p2p_inventory import decode_inventory, INV_TYPE_BLOCK
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)
MAGIC = bytes.fromhex("b2a1c3d4")


def mined_block(height, previous, timestamp):
    coinbase = Transaction(
        1,
        (TxInput(
            OutPoint(ZERO_TXID, COINBASE_INDEX),
            bytes((1, height & 0xff)),
        ),),
        (TxOutput(block_subsidy(height), b"miner"),),
    )
    root = merkle_root([coinbase.txid])
    for nonce in range(10000):
        header = BlockHeader(1, previous, root, timestamp, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, (coinbase,))
    raise AssertionError("integration block mining exhausted")


class LiveBlockBodySyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_tcp_peer_sync_downloads_and_connects_real_block_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = int(time.time())
            genesis = mined_block(0, ZERO_HASH, now - 120)
            next_block = mined_block(1, genesis.header.hash, now - 60)

            source_state = PersistentNodeState(
                root / "source-headers.sqlite",
                root / "source-utxos.sqlite",
                POW_LIMIT,
                genesis.header,
            )
            destination_state = PersistentNodeState(
                root / "destination-headers.sqlite",
                root / "destination-utxos.sqlite",
                POW_LIMIT,
                genesis.header,
            )
            source_state.headers.add_to_branch(
                next_block.header, adjusted_time=now, max_future_seconds=7200
            )
            source_state.connect_best_block(genesis, 0)
            source_state.connect_best_block(next_block, 1)
            destination_state.connect_best_block(genesis, 0)

            served_requests = []
            source_header_sync = PeerHeaderSync(
                source_state.headers.chain,
                protocol_version=1,
                adjusted_time=lambda: int(time.time()),
            )

            def source_handler_factory(peer):
                async def dispatch(command, payload):
                    if command == "getheaders":
                        await source_header_sync.handle_message(peer, command, payload)
                    elif command == "getdata":
                        items = decode_inventory(payload)
                        requested = [
                            item.item_hash for item in items
                            if item.kind == INV_TYPE_BLOCK
                        ]
                        for block_hash in requested:
                            if block_hash == next_block.header.hash:
                                served_requests.append(block_hash)
                                await peer.send("block", next_block.serialize())
                return dispatch

            source_manager = PeerManager(
                magic=MAGIC,
                local_version=VersionMessage(
                    1, 0, now, 1001, 1, "/blackroot:body-source/"
                ),
                max_peers=4,
                handshake_timeout=2,
                idle_timeout=10,
                on_peer_message_factory=source_handler_factory,
            )
            destination_manager = PeerManager(
                magic=MAGIC,
                local_version=VersionMessage(
                    1, 0, now, 2002, 0, "/blackroot:body-destination/"
                ),
                max_peers=4,
                handshake_timeout=2,
                idle_timeout=10,
            )
            source_runtime = BlackrootNodeRuntime(
                source_state, source_manager, protocol_version=1, request_timeout=2
            )
            destination_runtime = BlackrootNodeRuntime(
                destination_state, destination_manager,
                protocol_version=1, request_timeout=2,
            )
            try:
                host, port = await source_runtime.listen("127.0.0.1", 0)
                peer = await destination_runtime.connect(host, port)
                deadline = asyncio.get_running_loop().time() + 3
                while not peer.connected:
                    if asyncio.get_running_loop().time() >= deadline:
                        self.fail("peer handshake did not complete")
                    await asyncio.sleep(0.01)

                await destination_runtime.synchronize()

                async def wait_for_active_body():
                    while destination_state.utxos.tip() != (
                        1, next_block.header.hash
                    ):
                        if asyncio.get_running_loop().time() >= deadline + 5:
                            self.fail(
                                "destination did not connect downloaded body; "
                                f"tip={destination_state.utxos.tip()}"
                            )
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_for_active_body(), timeout=6)
                self.assertEqual(served_requests, [next_block.header.hash])
                self.assertEqual(
                    destination_state.headers.chain.tip.hash,
                    next_block.header.hash,
                )
                self.assertEqual(
                    destination_state.utxos.tip(),
                    source_state.utxos.tip(),
                )
                stored = destination_state.utxos.load_block_body(
                    next_block.header.hash
                )
                self.assertIsNotNone(stored)
                self.assertEqual(stored.header.hash, next_block.header.hash)
                self.assertEqual(len(stored.transactions), 1)

                # Simulate a node restart by reopening both persistent stores
                # from the same data directory after closing the first state.
                destination_state.close()
                destination_state = PersistentNodeState(
                    root / "destination-headers.sqlite",
                    root / "destination-utxos.sqlite",
                    POW_LIMIT,
                    genesis.header,
                )
                self.assertEqual(
                    destination_state.headers.chain.tip.hash,
                    next_block.header.hash,
                )
                self.assertEqual(
                    destination_state.utxos.tip(),
                    (1, next_block.header.hash),
                )
                restored = destination_state.utxos.load_block_body(
                    next_block.header.hash
                )
                self.assertIsNotNone(restored)
                self.assertEqual(restored.serialize(), next_block.serialize())
                destination_state.utxos.verify_integrity()
            finally:
                await destination_runtime.close()
                await source_runtime.close()
                destination_state.close()
                source_state.close()


if __name__ == "__main__":
    unittest.main()
