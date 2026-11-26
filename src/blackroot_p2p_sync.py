"""Apply decoded P2P headers to the local header DAG.

The batch is validated by HeaderChain and is all-or-nothing in memory. This
module does not implement peer sockets, locator requests, block-body fetching,
or transaction/UTXO validation.
"""
from __future__ import annotations

from collections.abc import Callable

from .blackroot_chain import HeaderChain
from .blackroot_p2p_headers import decode_headers


def accept_headers_payload(
    chain: HeaderChain,
    payload: bytes,
    *,
    adjusted_time: int | None = None,
    max_future_seconds: int = 7_200,
    on_commit: Callable[[HeaderChain], None] | None = None,
) -> list[str]:
    """Decode and consensus-check a peer headers payload as one atomic batch."""
    if not isinstance(chain, HeaderChain):
        raise TypeError("chain must be a HeaderChain")
    headers = decode_headers(payload)
    return chain.add_batch(
        headers,
        adjusted_time=adjusted_time,
        max_future_seconds=max_future_seconds,
        on_commit=on_commit,
    )
