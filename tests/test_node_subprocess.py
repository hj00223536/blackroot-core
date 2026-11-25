"""End-to-end CLI smoke test using two independent OS processes.

This exercises only a local, valueless testnet candidate on loopback. It does
not establish public-network readiness or complete block/consensus validation.
"""
import hashlib
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENESIS_TIMESTAMP = 1_795_564_800
GENESIS_BITS = 0x207FFFFF
GENESIS_MERKLE = bytes.fromhex(
    "2ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a9935"
)
POW_LIMIT = 0x7FFFFF << (8 * (0x20 - 3))


def _sha256d(raw):
    return hashlib.sha256(hashlib.sha256(raw).digest()).digest()


def _write_config(path):
    header = (
        (1).to_bytes(4, "little")
        + bytes(32)
        + GENESIS_MERKLE
        + GENESIS_TIMESTAMP.to_bytes(4, "little")
        + GENESIS_BITS.to_bytes(4, "little")
        + (0).to_bytes(4, "little")
    )
    assert len(header) == 80
    block_hash = _sha256d(header)
    assert int.from_bytes(block_hash, "little") <= POW_LIMIT
    config = {
        "network_id": "blackroot-local-process-smoke",
        "message_magic": "b2a1c3d4",
        "protocol_version": 1,
        "genesis_header": {
            "version": 1,
            "prev_hash": bytes(32).hex(),
            "merkle_root": GENESIS_MERKLE.hex(),
            "timestamp": GENESIS_TIMESTAMP,
            "bits": GENESIS_BITS,
            "nonce": 0,
        },
        "genesis_hash": block_hash.hex(),
        "pow_limit": hex(POW_LIMIT),
        "p2p_port": 0,
        "max_peers": 4,
    }
    path.write_text(json.dumps(config), encoding="utf-8")


def _read_json_line(process, timeout=12):
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        ready = selector.select(timeout)
        if not ready:
            raise AssertionError(
                f"node did not emit startup record within {timeout}s; "
                f"returncode={process.poll()}"
            )
        line = process.stdout.readline()
        if not line:
            raise AssertionError(
                f"node exited before startup record; returncode={process.poll()}"
            )
        return json.loads(line)
    finally:
        selector.close()


class SeparateProcessNodeSmokeTests(unittest.TestCase):
    def test_two_cli_processes_handshake_and_share_genesis(self):
        processes = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "testnet.json"
            _write_config(config_path)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

            def start_node(name, *extra):
                process = subprocess.Popen(
                    [
                        sys.executable, "-m", "src.blackroot_node",
                        "--config", str(config_path),
                        "--data-dir", str(root / name),
                        "--bind-host", "127.0.0.1",
                        *extra,
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                processes.append(process)
                return process

            try:
                first = start_node("node-a")
                first_record = _read_json_line(first)
                self.assertEqual(first_record["event"], "node_started")
                self.assertEqual(first_record["listen_host"], "127.0.0.1")
                self.assertGreater(first_record["listen_port"], 0)

                second = start_node(
                    "node-b", "--connect",
                    f'127.0.0.1:{first_record["listen_port"]}',
                )
                second_record = _read_json_line(second)
                self.assertEqual(second_record["event"], "node_started")
                self.assertEqual(second_record["peer_count"], 1)
                self.assertEqual(
                    second_record["network_id"], first_record["network_id"]
                )
                self.assertEqual(
                    second_record["genesis_hash"], first_record["genesis_hash"]
                )
                self.assertEqual(
                    second_record["best_hash"], first_record["best_hash"]
                )
                self.assertEqual(second_record["height"], 0)
                self.assertEqual(first_record["height"], 0)
                self.assertIn("no value", second_record["warning"])

                # Exercise the CLI's SIGTERM path, not just test-runner cleanup.
                for process in reversed(processes):
                    process.terminate()
                for process in reversed(processes):
                    process.communicate(timeout=5)
                    self.assertEqual(
                        process.returncode, 0,
                        f"node did not shut down cleanly; output={process.stdout}",
                    )

            finally:
                # Always reap children, including when an assertion or timeout fails.
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                for process in reversed(processes):
                    if process.poll() is None:
                        try:
                            process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
