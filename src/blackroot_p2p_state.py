"""Deterministic peer version/verack handshake state machine.

This is a transport-independent prototype. Callers remain responsible for
socket deadlines, peer identity, address policy, encryption, and DoS controls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .blackroot_p2p_handshake import VersionMessage, decode_version, encode_version


@dataclass
class PeerHandshake:
    """Track the required local/remote version and verack exchange."""

    local_version: VersionMessage
    local_version_sent: bool = False
    remote_version: VersionMessage | None = None
    local_verack_sent: bool = False
    remote_verack_received: bool = False
    _complete: bool = field(default=False, init=False, repr=False)

    @property
    def complete(self) -> bool:
        return self._complete

    def mark_local_version_sent(self) -> None:
        if self.local_version_sent:
            raise ValueError("local version was already sent")
        self.local_version_sent = True
        self._refresh_complete()

    def receive_version(self, payload: bytes) -> VersionMessage:
        if self.remote_version is not None:
            raise ValueError("remote version was already received")
        remote = decode_version(payload)
        if remote.nonce == self.local_version.nonce:
            raise ValueError("self-connection detected")
        self.remote_version = remote
        self._refresh_complete()
        return remote

    def mark_local_verack_sent(self) -> None:
        if self.remote_version is None:
            raise ValueError("cannot send verack before receiving remote version")
        if not self.local_version_sent:
            raise ValueError("cannot send verack before local version")
        if self.local_verack_sent:
            raise ValueError("local verack was already sent")
        self.local_verack_sent = True
        self._refresh_complete()

    def receive_verack(self, payload: bytes) -> None:
        if payload != b"":
            raise ValueError("verack payload must be empty")
        if self.remote_version is None:
            raise ValueError("received verack before remote version")
        if not self.local_version_sent:
            raise ValueError("received verack before local version was sent")
        if self.remote_verack_received:
            raise ValueError("remote verack was already received")
        self.remote_verack_received = True
        self._refresh_complete()

    def _refresh_complete(self) -> None:
        self._complete = (
            self.local_version_sent
            and self.remote_version is not None
            and self.local_verack_sent
            and self.remote_verack_received
        )


def encode_local_version(handshake: PeerHandshake) -> bytes:
    """Return the local version payload and record that the caller sent it."""
    if handshake.local_version_sent:
        raise ValueError("local version was already sent")
    payload = encode_version(handshake.local_version)
    handshake.mark_local_version_sent()
    return payload
