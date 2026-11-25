"""Bounded, checksummed P2P message framing for the BLACKROOT prototype.

This module parses message envelopes only. It does not open sockets, implement
peer discovery, authenticate peers, or validate consensus messages.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .blackroot_consensus import sha256d

HEADER_SIZE = 24
DEFAULT_MAX_PAYLOAD = 2_000_000
_COMMAND = re.compile(r"[a-z0-9_]{1,12}\\Z")


def _validate_magic(magic: bytes) -> None:
    if not isinstance(magic, bytes) or len(magic) != 4:
        raise ValueError("network magic must be exactly four bytes")


def _validate_command(command: str) -> bytes:
    if not isinstance(command, str) or _COMMAND.fullmatch(command) is None:
        raise ValueError("command must be 1-12 lowercase ASCII letters, digits, or underscores")
    return command.encode("ascii").ljust(12, b"\\x00")


def _validate_limit(max_payload: int) -> None:
    if not isinstance(max_payload, int) or isinstance(max_payload, bool) or not 0 <= max_payload <= 0xFFFFFFFF:
        raise ValueError("maximum payload must fit uint32")


def encode_message(magic: bytes, command: str, payload: bytes, *, max_payload: int = DEFAULT_MAX_PAYLOAD) -> bytes:
    """Encode one bounded message using a 4-byte SHA256d payload checksum."""
    _validate_magic(magic)
    _validate_limit(max_payload)
    command_bytes = _validate_command(command)
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) > max_payload:
        raise ValueError("message payload exceeds configured limit")
    return magic + command_bytes + struct.pack("<I", len(payload)) + sha256d(payload)[:4] + payload


def decode_message(frame: bytes, magic: bytes, *, max_payload: int = DEFAULT_MAX_PAYLOAD) -> tuple[str, bytes]:
    """Decode exactly one complete message; reject malformed or trailing bytes."""
    _validate_magic(magic)
    _validate_limit(max_payload)
    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if len(frame) < HEADER_SIZE:
        raise ValueError("truncated message header")
    if frame[:4] != magic:
        raise ValueError("message network magic mismatch")
    raw_command = frame[4:16]
    command_part, separator, padding = raw_command.partition(b"\\x00")
    if separator and any(padding):
        raise ValueError("message command has non-zero bytes after padding")
    try:
        command = command_part.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("message command is not ASCII") from exc
    _validate_command(command)
    length = struct.unpack_from("<I", frame, 16)[0]
    if length > max_payload:
        raise ValueError("message payload exceeds configured limit")
    if len(frame) != HEADER_SIZE + length:
        raise ValueError("message frame length mismatch")
    payload = frame[HEADER_SIZE:]
    if frame[20:24] != sha256d(payload)[:4]:
        raise ValueError("message payload checksum mismatch")
    return command, payload


@dataclass
class MessageStreamParser:
    """Incremental bounded parser for fragmented or concatenated message frames."""
    magic: bytes
    max_payload: int = DEFAULT_MAX_PAYLOAD
    _buffer: bytearray = field(default_factory=bytearray, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_magic(self.magic)
        _validate_limit(self.max_payload)

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[tuple[str, bytes]]:
        if not isinstance(data, bytes):
            raise TypeError("stream data must be bytes")
        if len(self._buffer) + len(data) > HEADER_SIZE + self.max_payload:
            raise ValueError("receive buffer exceeds configured message bound")
        self._buffer.extend(data)
        messages = []
        while len(self._buffer) >= HEADER_SIZE:
            if self._buffer[:4] != self.magic:
                self._buffer.clear()
                raise ValueError("message network magic mismatch")
            length = struct.unpack_from("<I", self._buffer, 16)[0]
            if length > self.max_payload:
                self._buffer.clear()
                raise ValueError("message payload exceeds configured limit")
            frame_length = HEADER_SIZE + length
            if len(self._buffer) < frame_length:
                break
            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            messages.append(decode_message(frame, self.magic, max_payload=self.max_payload))
        return messages

    def reset(self) -> None:
        """Discard any incomplete frame after a peer disconnect or parse failure."""
        self._buffer.clear()
