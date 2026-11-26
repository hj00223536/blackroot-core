import asyncio
import tempfile
import unittest
from pathlib import Path

from src.blackroot_blocks import Block, COINBASE_INDEX, ZERO_TXID
from src.blackroot_chain import BlockHeader, ZERO_HASH
from src.blackroot_consensus import COIN, check_proof_of_work, decode_compact_target
from src.blackroot_node_runtime import BlackrootNodeRuntime
from src.blackroot_node import wait_for_peer_handshake
from src.blackroot_node_state import PersistentNodeState
from src.blackroot_p2p_handshake import VersionMessage
from src.blackroot_p2p_manager import PeerManager
from src.blackroot_transactions import OutPoint, Transaction, TxInput, TxOutput, merkle_root

BITS = 0x207FFFFF
POW_LIMIT = decode_compact_target(BITS)
MAGIC = bytes.fromhex("b2a1c3d4")


def genesis_block():
    tx = Transaction(
        1,
        (TxInput(OutPoint(ZERO_TXID, COINBASE_INDEX), b"\\x01\\x01"),),
        (TxOutput(0, bytes.fromhex("6a")),),
    )
    for nonce in range(10_000):
        header = BlockHeader(1, ZERO_HASH, merkle_root([tx.txid]), 1, BITS, nonce)
        if check_proof_of_work(header.serialize(), BITS, POW_LIMIT):
            return Block(header, (tx,))
    raise AssertionError("could not mine test genesis")


class BlackrootNodeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        genesis = genesis_block()
        self.state = PersistentNodeState(
            root / "headers.sqlite", root / "utxos.sqlite",
            POW_LIMIT, genesis.header,
            adjusted_time_provider=lambda: 1_800_000_100,
        )
        manager = PeerManager(
            magic=MAGIC,
            local_version=VersionMessage(
                1, 0, 1_800_000_000, 101, 0, "/blackroot:runtime-test/"
            ),
            max_peers=4,
            handshake_timeout=1,
            idle_timeout=2,
        )
        self.runtime = BlackrootNodeRuntime(
            self.state, manager, protocol_version=1, request_timeout=1,
            adjusted_time=lambda: 1_800_000_100
        )

    async def asyncTearDown(self):
        await self.runtime.close()

    async def test_runtime_sync_store_routes_activation_through_node_state(self):
        adapter = self.runtime.sync.store
        self.assertIsNot(adapter, self.state.utxos)
        self.assertTrue(callable(adapter.connect_validated_block))
        self.assertTrue(callable(adapter.reorganize_to_best))

        block = genesis_block()
        calls = []
        original = self.state.connect_best_block

        def tracked_connect(candidate, height):
            calls.append((candidate.header.hash, height))
            return original(candidate, height)

        self.state.connect_best_block = tracked_connect
        try:
            result = adapter.connect_validated_block(
                block, 0, self.state.headers.chain
            )
        finally:
            self.state.connect_best_block = original

        self.assertEqual(result, 0)
        self.assertEqual(calls, [(block.header.hash, 0)])
        self.assertEqual(self.state.utxos.tip(), (0, block.header.hash))
        self.assertFalse(self.state.recovery_journal.pending())

    async def test_runtime_sync_store_rejects_foreign_header_chain(self):
        from src.blackroot_chain import HeaderChain

        foreign = HeaderChain(POW_LIMIT, self.state.headers.chain.get(0))
        with self.assertRaisesRegex(ValueError, "not the node state's validated chain"):
            self.runtime.sync.store.connect_validated_block(
                genesis_block(), 0, foreign
            )
        self.assertIsNone(self.state.utxos.tip())

    async def test_runtime_binds_sync_callbacks_and_starts_listener(self):
        self.assertIs(
            self.runtime.manager.on_peer_message_factory.__self__,
            self.runtime.sync,
        )
        self.assertIs(
            self.runtime.manager.on_peer_disconnected.__self__,
            self.runtime.sync,
        )
        address = await self.runtime.listen()
        self.assertTrue(self.runtime.listening)
        self.assertEqual(address[0], "127.0.0.1")
        self.assertEqual(await self.runtime.synchronize(), {})
        self.assertEqual(self.runtime.peer_count, 0)

    async def test_runtime_restart_replays_persistent_headers_and_utxo_tip(self):
        genesis = self.state.headers.chain.get(0)
        self.assertEqual(self.state.connect_best_block(
            genesis_block(), 0
        ), 0)

        await self.runtime.close()

        root = Path(self.temp.name)
        reopened_state = PersistentNodeState(
            root / "headers.sqlite",
            root / "utxos.sqlite",
            POW_LIMIT,
            genesis,
            adjusted_time_provider=lambda: 1_800_000_100,
        )
        self.assertEqual(
            reopened_state.utxos.tip(),
            (0, genesis.hash),
        )
        self.assertEqual(
            reopened_state.headers.chain.get(0).hash,
            genesis.hash,
        )

        manager = PeerManager(
            magic=MAGIC,
            local_version=VersionMessage(
                1, 0, 1_800_000_001, 102, 0, "/blackroot:restart-test/"
            ),
            max_peers=4,
            handshake_timeout=1,
            idle_timeout=2,
        )
        restarted = BlackrootNodeRuntime(
            reopened_state, manager, protocol_version=1, request_timeout=1,
            adjusted_time=lambda: 1_800_000_100
        )
        try:
            address = await restarted.listen()
            self.assertTrue(restarted.listening)
            self.assertEqual(address[0], "127.0.0.1")
            self.assertEqual(restarted.state.utxos.tip(), (0, genesis.hash))
        finally:
            await restarted.close()

    async def test_retry_loop_runs_and_stops_cleanly(self):
        calls = asyncio.Event()

        async def retry_expired(*, now=None):
            calls.set()
            return {}

        self.runtime.sync.retry_expired = retry_expired
        await self.runtime.start_retry_loop(interval=0.01)
        await asyncio.wait_for(calls.wait(), timeout=1)
        task = self.runtime._retry_task
        await self.runtime.stop_retry_loop()
        self.assertIsNone(self.runtime._retry_task)
        self.assertTrue(task.cancelled())

    async def test_retry_loop_survives_transient_error_and_recovers(self):
        calls = 0
        recovered = asyncio.Event()

        async def retry_expired(*, now=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("temporary peer failure")
            recovered.set()
            return {}

        self.runtime.sync.retry_expired = retry_expired
        await self.runtime.start_retry_loop(interval=0.01)
        await asyncio.wait_for(recovered.wait(), timeout=1)
        self.assertGreaterEqual(calls, 2)
        self.assertIsNone(self.runtime.retry_last_error)
        self.assertIsNotNone(self.runtime._retry_task)
        self.assertFalse(self.runtime._retry_task.done())
        await self.runtime.stop_retry_loop()

    async def test_retry_loop_rejects_invalid_intervals(self):
        for invalid in (float("nan"), float("inf"), float("-inf"), True, 0, -1, "1"):
            with self.subTest(interval=invalid):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    await self.runtime.start_retry_loop(interval=invalid)

    async def test_close_stops_retry_loop(self):
        await self.runtime.start_retry_loop(interval=10)
        task = self.runtime._retry_task
        await self.runtime.close()
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.runtime._retry_task)

    async def test_close_is_idempotent_and_blocks_new_network_actions(self):
        await self.runtime.close()
        await self.runtime.close()
        self.assertFalse(self.runtime.listening)
        with self.assertRaisesRegex(RuntimeError, "runtime is closed"):
            await self.runtime.listen()
        with self.assertRaisesRegex(RuntimeError, "runtime is closed"):
            await self.runtime.synchronize()

    async def test_two_independent_runtimes_handshake_and_request_headers(self):
        root = Path(self.temp.name)
        genesis = self.state.headers.chain.get(0)
        remote_state = PersistentNodeState(
            root / "remote-headers.sqlite",
            root / "remote-utxos.sqlite",
            POW_LIMIT,
            genesis,
            adjusted_time_provider=lambda: 1_800_000_100,
        )
        remote_manager = PeerManager(
            magic=MAGIC,
            local_version=VersionMessage(
                1, 0, 1_800_000_002, 303, 0, "/blackroot:remote-test/"
            ),
            max_peers=4,
            handshake_timeout=2,
            idle_timeout=5,
        )
        remote = BlackrootNodeRuntime(
            remote_state, remote_manager, protocol_version=1, request_timeout=1,
            adjusted_time=lambda: 1_800_000_100
        )
        try:
            host, port = await remote.listen("127.0.0.1", 0)
            peer = await self.runtime.connect(host, port)
            await wait_for_peer_handshake(peer, timeout=2)

            async def wait_remote():
                while not any(item.connected for item in remote.manager.peers):
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_remote(), timeout=2)

            sent = await self.runtime.synchronize()
            self.assertEqual(tuple(sent), (peer,))
            self.assertEqual(peer.remote_version.protocol_version, 1)
            self.assertEqual(
                self.runtime.state.headers.chain.tip.hash,
                remote.state.headers.chain.tip.hash,
            )
            self.assertEqual(
                self.runtime.state.headers.chain.get(0).hash,
                remote.state.headers.chain.get(0).hash,
            )
        finally:
            await remote.close()
            remote_state.close()


if __name__ == "__main__":
    unittest.main()
