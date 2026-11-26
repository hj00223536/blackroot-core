"""Peer-level header synchronization coordinator for BLACKROOT.

This composes the existing bounded getheaders/headers codecs with the
consensus-checked HeaderChain. It does not fetch block bodies or mark a peer
trusted; those remain separate responsibilities.
"""
from __future__ import annotations

from collections.abc import Callable

from .blackroot_chain import HeaderChain
from .blackroot_p2p_getheaders import GetHeadersMessage, decode_getheaders, encode_getheaders
from .blackroot_p2p_headers import MAX_HEADERS_PER_MESSAGE, encode_headers
from .blackroot_p2p_sync import accept_headers_payload

ZERO_HASH = bytes(32)


def build_block_locator(chain: HeaderChain, *, max_hashes: int = 101) -> tuple[bytes, ...]:
    """Build a Bitcoin-style exponentially stepped locator from the best tip."""
    if not isinstance(chain, HeaderChain):
        raise TypeError("chain must be a HeaderChain")
    if not isinstance(max_hashes, int) or isinstance(max_hashes, bool) or not 1 <= max_hashes <= 101:
        raise ValueError("max_hashes must be between 1 and 101")
    hashes: list[bytes] = []
    height = chain.height
    step = 1
    while height > 0 and len(hashes) < max_hashes - 1:
        hashes.append(chain.get(height).hash)
        height = max(0, height - step)
        if len(hashes) >= 10:
            step *= 2
    hashes.append(chain.get(0).hash)
    return tuple(hashes[:max_hashes])


class PeerHeaderSync:
    """Handle getheaders/headers messages for one established peer session."""

    def __init__(
        self,
        chain: HeaderChain,
        *,
        protocol_version: int,
        adjusted_time: Callable[[], int] | None = None,
        max_future_seconds: int = 7_200,
        on_headers_validated: Callable[[HeaderChain], None] | None = None,
    ) -> None:
        if not isinstance(chain, HeaderChain):
            raise TypeError("chain must be a HeaderChain")
        if not isinstance(protocol_version, int) or isinstance(protocol_version, bool) or not 1 <= protocol_version <= 0x7FFFFFFF:
            raise ValueError("protocol_version must be a positive int32")
        if adjusted_time is not None and not callable(adjusted_time):
            raise TypeError("adjusted_time must be callable")
        chain_adjusted_time = chain.adjusted_time_provider
        if on_headers_validated is not None and not callable(chain_adjusted_time):
            raise ValueError(
                "persistent peer header sync requires the header chain's adjusted-time provider"
            )
        if adjusted_time is None:
            adjusted_time = chain_adjusted_time
        elif chain_adjusted_time is not None and adjusted_time is not chain_adjusted_time:
            raise ValueError(
                "peer header sync adjusted-time provider must match the header chain provider"
            )
        if on_headers_validated is not None and adjusted_time is not chain_adjusted_time:
            raise ValueError(
                "persistent peer header sync clock must match the header chain provider"
            )
        if not isinstance(max_future_seconds, int) or isinstance(max_future_seconds, bool) or max_future_seconds < 0:
            raise ValueError("max_future_seconds must be non-negative")
        if on_headers_validated is not None and not callable(on_headers_validated):
            raise TypeError("on_headers_validated must be callable")
        self.chain = chain
        self.protocol_version = protocol_version
        self.adjusted_time = adjusted_time
        self.max_future_seconds = max_future_seconds
        self.on_headers_validated = on_headers_validated
        self._last_locator: tuple[bytes, ...] = ()

    def _now(self) -> int:
        """Return the caller-supplied clock value; never silently skip future-time checks."""
        if self.adjusted_time is None:
            raise RuntimeError(
                "header synchronization requires an adjusted-time provider"
            )
        now = self.adjusted_time()
        if not isinstance(now, int) or isinstance(now, bool) or now < 0:
            raise ValueError("adjusted-time provider must return a non-negative integer")
        return now

    async def request_headers(self, peer) -> bytes:
        """Send a locator request to an established peer and return its payload."""
        if not getattr(peer, "connected", False):
            raise ConnectionError("peer handshake is not complete")
        locator = build_block_locator(self.chain)
        message = GetHeadersMessage(self.protocol_version, locator, ZERO_HASH)
        payload = encode_getheaders(message)
        self._last_locator = locator
        await peer.send("getheaders", payload)
        return payload

    def make_headers_response(self, payload: bytes) -> bytes:
        """Create a bounded headers response after the first known locator hash."""
        request = decode_getheaders(payload)
        best = self.chain.best_chain()
        heights = {header.hash: height for height, header in enumerate(best)}
        common_height = next(
            (heights[item] for item in request.locator_hashes if item in heights),
            None,
        )
        if common_height is None:
            headers = []
        else:
            headers = []
            for header in best[common_height + 1:common_height + 1 + MAX_HEADERS_PER_MESSAGE]:
                headers.append(header)
                if request.stop_hash != ZERO_HASH and header.hash == request.stop_hash:
                    break
        return encode_headers(headers)

    async def handle_message(self, peer, command: str, payload: bytes) -> None:
        """Dispatch the two header-sync commands; reject unknown commands."""
        if not getattr(peer, "connected", False):
            raise ConnectionError("peer handshake is not complete")
        if command == "getheaders":
            await peer.send("headers", self.make_headers_response(payload))
            return
        if command == "headers":
            accepted = accept_headers_payload(
                self.chain,
                payload,
                adjusted_time=self._now(),
                max_future_seconds=self.max_future_seconds,
                on_commit=self.on_headers_validated,
            )
            # A full batch may indicate more headers are available.
            if len(accepted) == MAX_HEADERS_PER_MESSAGE:
                await self.request_headers(peer)
            return
        raise ValueError(f"unsupported header-sync command: {command}")
