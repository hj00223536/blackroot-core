"""Three independent persistent nodes synchronize a block over real TCP.

The source and both destinations use separate persistent header/UTXO stores,
real PeerManager sockets, and the normal runtime sync path. This is a focused
local integration test, not proof of complete consensus or public readiness.
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


class ThreeNodeLiveBlockBodySyncTests(unittest.IsolatedAsyncioTestCase):
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
            destination_states = [
                PersistentNodeState(
                    root / f"destination-{index}-headers.sqlite",
                    root / f"destination-{index}-utxos.sqlite",
                    POW_LIMIT,
                    genesis.header,
                )
                for index in (1, 2)
            ]
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
            destination_managers = [
                PeerManager(
                    magic=MAGIC,
                    local_version=VersionMessage(
                        1, 0, now, 2000 + index, 0,
                        f"/blackroot:body-destination-{index}/"
                    ),
                    max_peers=4,
                    handshake_timeout=2,
                    idle_timeout=10,
                )
                for index in (1, 2)
            ]
            source_runtime = BlackrootNodeRuntime(
                source_state, source_manager, protocol_version=1, request_timeout=2
            )
            destination_runtimes = [
                BlackrootNodeRuntime(
                    state, manager, protocol_version=1, request_timeout=2,
                    adjusted_time=lambda: int(time.time()),
                )
                for state, manager in zip(destination_states, destination_managers)
            ]
            try:
                host, port = await source_runtime.listen("127.0.0.1", 0)
                peers = [
                    await runtime.connect(host, port)
                    for runtime in destination_runtimes
                ]
                deadline = asyncio.get_running_loop().time() + 3
                while not all(peer.connected for peer in peers):
                    if asyncio.get_running_loop().time() >= deadline:
                        self.fail("all three node handshakes did not complete")
                    await asyncio.sleep(0.01)

                await asyncio.gather(
                    *(runtime.synchronize() for runtime in destination_runtimes)
                )

                async def wait_for_active_bodies():
                    while any(
                        state.utxos.tip() != (1, next_block.header.hash)
                        for state in destination_states
                    ):
                        if asyncio.get_running_loop().time() >= deadline + 5:
                            self.fail(
                                "one or more destinations did not connect downloaded body; "
                                f"tips={[state.utxos.tip() for state in destination_states]}"
                            )
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_for_active_bodies(), timeout=6)
                self.assertEqual(
                    len(served_requests), 2,
                    "source must serve the same block body independently to both peers",
                )
                for state in destination_states:
                    self.assertEqual(
                        state.headers.chain.tip.hash, next_block.header.hash
                    )
                    self.assertEqual(state.utxos.tip(), source_state.utxos.tip())
                    stored = state.utxos.load_block_body(next_block.header.hash)
                    self.assertIsNotNone(stored)
                    self.assertEqual(stored.header.hash, next_block.header.hash)
                    self.assertEqual(len(stored.transactions), 1)

                # Restart both independent destination nodes and verify their
                # persistent active tips and archived block bodies.
                for index, state in enumerate(destination_states, start=1):
                    state.close()
                    destination_states[index - 1] = PersistentNodeState(
                        root / f"destination-{index}-headers.sqlite",
                        root / f"destination-{index}-utxos.sqlite",
                        POW_LIMIT,
                        genesis.header,
                    )
                    reopened = destination_states[index - 1]
                    self.assertEqual(
                        reopened.headers.chain.tip.hash, next_block.header.hash
                    )
                    self.assertEqual(reopened.utxos.tip(), (1, next_block.header.hash))
                    restored = reopened.utxos.load_block_body(next_block.header.hash)
                    self.assertIsNotNone(restored)
                    self.assertEqual(restored.serialize(), next_block.serialize())
                    reopened.utxos.verify_integrity()
            finally:
                for runtime in destination_runtimes:
                    await runtime.close()
                await source_runtime.close()
                for state in destination_states:
                    state.close()
                source_state.close()


if __name__ == "__main__":
    unittest.main()
