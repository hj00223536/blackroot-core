"""Loopback-only local testnet node runner; not a public full-node release."""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import secrets
import time
from pathlib import Path

from .blackroot_node_config import TestnetConfig
from .blackroot_node_runtime import BlackrootNodeRuntime
from .blackroot_node_state import PersistentNodeState
from .blackroot_p2p_handshake import VersionMessage


def parse_connect_endpoint(endpoint: str, config: TestnetConfig) -> tuple[str, int]:
    """Parse and validate a literal loopback peer endpoint."""
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("peer endpoint must be non-empty text")
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing < 0 or endpoint[closing + 1:closing + 2] != ":":
            raise ValueError("IPv6 peer endpoint must use [::1]:PORT")
        host, port_text = endpoint[1:closing], endpoint[closing + 2:]
    else:
        if endpoint.count(":") != 1:
            raise ValueError("peer endpoint must use IP:PORT")
        host, port_text = endpoint.rsplit(":", 1)
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ValueError("peer port must be between 1 and 65535")
    config.validate_bind_host(host)
    return host, int(port_text)


async def wait_for_peer_handshake(peer, *, timeout: float = 10.0) -> None:
    """Wait until the managed session completes version/verack or closes."""
    async def poll() -> None:
        while not peer.connected:
            if peer.writer.is_closing():
                raise ConnectionError("peer disconnected before handshake completed")
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout=timeout)


async def run_node(config: TestnetConfig, data_dir: Path, bind_host: str, connect_to: tuple[str, int] | None = None) -> None:
    bind_host = config.validate_bind_host(bind_host)
    data_dir.mkdir(parents=True, exist_ok=True)
    state = PersistentNodeState.open_coordinated(
        data_dir / "blackroot-node.sqlite",
        config.pow_limit,
        config.genesis_header,
    )
    runtime = None
    try:
        version = VersionMessage(
            protocol_version=config.protocol_version,
            services=0,
            timestamp=int(time.time()),
            nonce=secrets.randbits(64),
            start_height=state.headers.chain.height,
            user_agent="/blackroot-local-node/0.1/",
        )
        manager = config.create_peer_manager(version)
        runtime = BlackrootNodeRuntime(
            state,
            manager,
            protocol_version=config.protocol_version,
            # Provisional local UTC clock for the future-time bound. A
            # production network must replace this with a network-adjusted
            # clock derived from its peer-time policy.
            adjusted_time=lambda: int(time.time()),
        )
        host, port = await runtime.listen(bind_host, config.p2p_port)
        if connect_to is not None:
            remote_host, remote_port = connect_to
            config.validate_bind_host(remote_host)
            peer = await runtime.connect(remote_host, remote_port)
            await wait_for_peer_handshake(peer)
            await runtime.synchronize()
        # Install handlers before publishing readiness: a supervisor may send
        # SIGTERM immediately after reading the startup record.
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass

        print(json.dumps({
            "event": "node_started",
            "network_id": config.network_id,
            "genesis_hash": config.genesis_header.display_hash,
            "height": state.headers.chain.height,
            "best_hash": state.headers.chain.tip.display_hash,
            "listen_host": host,
            "listen_port": port,
            "peer_count": runtime.peer_count,
            "data_dir": str(data_dir.resolve()),
            "warning": "local prototype; test coins have no value; not a public network",
        }, sort_keys=True), flush=True)

        await stop.wait()
    finally:
        if runtime is not None:
            await runtime.close()
        state.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an explicitly configured BLACKROOT local testnet node (loopback only)."
    )
    parser.add_argument("--config", required=True, help="strict JSON testnet config")
    parser.add_argument("--data-dir", required=True, help="node-owned data directory")
    parser.add_argument("--bind-host", default="127.0.0.1", help="literal loopback IP only")
    parser.add_argument("--connect", help="optional loopback peer as IP:PORT (IPv6: [::1]:PORT)")
    args = parser.parse_args(argv)
    try:
        config = TestnetConfig.from_json_file(args.config)
        config.validate_bind_host(args.bind_host)
        connect_to = parse_connect_endpoint(args.connect, config) if args.connect else None
        asyncio.run(run_node(config, Path(args.data_dir), args.bind_host, connect_to))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"blackroot-node: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
