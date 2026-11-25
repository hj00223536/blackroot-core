"""Deterministic transaction encoding and basic UTXO accounting primitives.

This module checks serialization and value accounting only. Block-level
consensus validation and the prototype's restricted P2PKH authorization
checks live in blackroot_blocks and blackroot_script respectively. The
implementation is not a complete Bitcoin Script or consensus engine.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable

from .blackroot_consensus import COIN, MAX_MONEY, sha256d

MAX_SCRIPT_SIZE = 10_000
MAX_VECTOR_ITEMS = 100_000
MAX_TRANSACTION_SIZE = 4_000_000
MAX_MONEY_ATOMS = MAX_MONEY


def _read_compact_size(raw: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(raw):
        raise ValueError("truncated CompactSize")
    prefix = raw[offset]
    offset += 1
    if prefix < 253:
        return prefix, offset
    widths = {253: 2, 254: 4, 255: 8}
    width = widths[prefix]
    if offset + width > len(raw):
        raise ValueError("truncated CompactSize payload")
    value = int.from_bytes(raw[offset:offset + width], "little")
    minimum = {253: 253, 254: 0x10000, 255: 0x100000000}[prefix]
    if value < minimum:
        raise ValueError("non-canonical CompactSize encoding")
    return value, offset + width


def _read_varbytes(raw: bytes, offset: int, *, limit: int = MAX_SCRIPT_SIZE) -> tuple[bytes, int]:
    length, offset = _read_compact_size(raw, offset)
    if length > limit:
        raise ValueError("serialized byte vector exceeds size limit")
    end = offset + length
    if end > len(raw):
        raise ValueError("truncated byte vector")
    return raw[offset:end], end


def _deserialize_transaction_from(raw: bytes, offset: int = 0) -> tuple["Transaction", int]:
    if not isinstance(raw, bytes):
        raise TypeError("serialized transaction must be bytes")
    start = offset
    if offset < 0 or offset + 4 > len(raw):
        raise ValueError("truncated transaction version")
    version = struct.unpack_from("<i", raw, offset)[0]
    offset += 4
    input_count, offset = _read_compact_size(raw, offset)
    if not 1 <= input_count <= MAX_VECTOR_ITEMS:
        raise ValueError("unsupported transaction input count")
    inputs = []
    for _ in range(input_count):
        if offset + 36 > len(raw):
            raise ValueError("truncated transaction outpoint")
        txid = raw[offset:offset + 32]
        index = struct.unpack_from("<I", raw, offset + 32)[0]
        offset += 36
        script_sig, offset = _read_varbytes(raw, offset)
        if offset + 4 > len(raw):
            raise ValueError("truncated transaction input sequence")
        sequence = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        inputs.append(TxInput(OutPoint(txid, index), script_sig, sequence))
    output_count, offset = _read_compact_size(raw, offset)
    if not 1 <= output_count <= MAX_VECTOR_ITEMS:
        raise ValueError("unsupported transaction output count")
    outputs = []
    for _ in range(output_count):
        if offset + 8 > len(raw):
            raise ValueError("truncated transaction output value")
        value = struct.unpack_from("<Q", raw, offset)[0]
        offset += 8
        script_pubkey, offset = _read_varbytes(raw, offset)
        outputs.append(TxOutput(value, script_pubkey))
    if offset + 4 > len(raw):
        raise ValueError("truncated transaction lock_time")
    lock_time = struct.unpack_from("<I", raw, offset)[0]
    offset += 4
    if offset - start > MAX_TRANSACTION_SIZE:
        raise ValueError("serialized transaction exceeds prototype size limit")
    return Transaction(version, tuple(inputs), tuple(outputs), lock_time), offset


def compact_size(value: int) -> bytes:
    """Encode an unsigned Bitcoin-style CompactSize integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("CompactSize value must be a non-negative integer")
    if value < 253:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    if value <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", value)
    if value <= 0xFFFFFFFFFFFFFFFF:
        return b"\xff" + struct.pack("<Q", value)
    raise ValueError("CompactSize value exceeds uint64")


def _varbytes(value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError("script must be bytes")
    if len(value) > MAX_SCRIPT_SIZE:
        raise ValueError("script exceeds prototype size limit")
    return compact_size(len(value)) + value


@dataclass(frozen=True)
class OutPoint:
    """txid is the raw 32-byte SHA256d digest, not reversed display hex."""
    txid: bytes
    index: int

    def __post_init__(self):
        if not isinstance(self.txid, bytes) or len(self.txid) != 32:
            raise ValueError("txid must be exactly 32 raw bytes")
        if not isinstance(self.index, int) or isinstance(self.index, bool) or not 0 <= self.index <= 0xFFFFFFFF:
            raise ValueError("output index must fit uint32")

    def serialize(self) -> bytes:
        return self.txid + struct.pack("<I", self.index)


@dataclass(frozen=True)
class TxInput:
    previous_output: OutPoint
    script_sig: bytes = b""
    sequence: int = 0xFFFFFFFF

    def __post_init__(self):
        if not isinstance(self.previous_output, OutPoint):
            raise TypeError("previous_output must be an OutPoint")
        if not isinstance(self.script_sig, bytes):
            raise TypeError("script_sig must be bytes")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or not 0 <= self.sequence <= 0xFFFFFFFF:
            raise ValueError("sequence must fit uint32")

    def serialize(self) -> bytes:
        return self.previous_output.serialize() + _varbytes(self.script_sig) + struct.pack("<I", self.sequence)


@dataclass(frozen=True)
class TxOutput:
    value: int
    script_pubkey: bytes

    def __post_init__(self):
        if not isinstance(self.value, int) or isinstance(self.value, bool) or not 0 <= self.value <= MAX_MONEY_ATOMS:
            raise ValueError("output value is outside the money range")
        if not isinstance(self.script_pubkey, bytes):
            raise TypeError("script_pubkey must be bytes")
        if len(self.script_pubkey) > MAX_SCRIPT_SIZE:
            raise ValueError("script exceeds prototype size limit")

    def serialize(self) -> bytes:
        return struct.pack("<Q", self.value) + _varbytes(self.script_pubkey)


@dataclass(frozen=True)
class Transaction:
    version: int
    inputs: tuple[TxInput, ...]
    outputs: tuple[TxOutput, ...]
    lock_time: int = 0

    def __post_init__(self):
        if not isinstance(self.version, int) or isinstance(self.version, bool) or not -(2**31) <= self.version < 2**31:
            raise ValueError("version must fit int32")
        if not isinstance(self.lock_time, int) or isinstance(self.lock_time, bool) or not 0 <= self.lock_time <= 0xFFFFFFFF:
            raise ValueError("lock_time must fit uint32")
        if not isinstance(self.inputs, tuple) or not isinstance(self.outputs, tuple):
            raise TypeError("inputs and outputs must be tuples")
        if not 1 <= len(self.inputs) <= MAX_VECTOR_ITEMS:
            raise ValueError("transaction must have a supported non-empty input vector")
        if not 1 <= len(self.outputs) <= MAX_VECTOR_ITEMS:
            raise ValueError("transaction must have a supported non-empty output vector")
        if not all(isinstance(item, TxInput) for item in self.inputs):
            raise TypeError("all inputs must be TxInput instances")
        if not all(isinstance(item, TxOutput) for item in self.outputs):
            raise TypeError("all outputs must be TxOutput instances")

    @classmethod
    def deserialize(cls, raw: bytes) -> "Transaction":
        """Parse one canonical legacy transaction; reject trailing or truncated bytes."""
        tx, offset = _deserialize_transaction_from(raw)
        if offset != len(raw):
            raise ValueError("trailing bytes after serialized transaction")
        return tx

    def serialize(self) -> bytes:
        result = struct.pack("<i", self.version) + compact_size(len(self.inputs))
        result += b"".join(txin.serialize() for txin in self.inputs)
        result += compact_size(len(self.outputs))
        result += b"".join(txout.serialize() for txout in self.outputs)
        result += struct.pack("<I", self.lock_time)
        if len(result) > MAX_TRANSACTION_SIZE:
            raise ValueError("serialized transaction exceeds prototype size limit")
        return result

    @property
    def txid(self) -> bytes:
        return sha256d(self.serialize())

    @property
    def display_txid(self) -> str:
        return self.txid[::-1].hex()


def merkle_root(txids: Iterable[bytes]) -> bytes:
    """Compute a Bitcoin-style merkle root from raw 32-byte transaction hashes."""
    level = list(txids)
    if not level:
        return bytes(32)
    if any(not isinstance(txid, bytes) or len(txid) != 32 for txid in level):
        raise ValueError("every transaction hash must be 32 raw bytes")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def validate_transaction(tx: Transaction, utxos: dict[OutPoint, TxOutput]) -> tuple[int, int]:
    """Check UTXO existence, duplicate spends and value conservation only.

    Returns (input_value, output_value). Script/signature authorization, fees
    policy, coinbase maturity, locktime and sequence semantics are NOT checked.
    """
    if not isinstance(tx, Transaction):
        raise TypeError("tx must be a Transaction")
    seen: set[OutPoint] = set()
    input_value = 0
    for txin in tx.inputs:
        outpoint = txin.previous_output
        if outpoint in seen:
            raise ValueError("duplicate input")
        seen.add(outpoint)
        previous = utxos.get(outpoint)
        if previous is None:
            raise ValueError("referenced UTXO does not exist")
        input_value += previous.value
        if input_value > MAX_MONEY_ATOMS:
            raise ValueError("input value exceeds money range")
    output_value = 0
    for output in tx.outputs:
        # Reuse output serialization checks for money and script bounds.
        output.serialize()
        output_value += output.value
        if output_value > MAX_MONEY_ATOMS:
            raise ValueError("output value exceeds money range")
    if output_value > input_value:
        raise ValueError("outputs exceed inputs")
    return input_value, output_value


def apply_transaction(tx: Transaction, utxos: dict[OutPoint, TxOutput]) -> int:
    """Validate value accounting, then atomically update this in-memory UTXO map.

    This prototype intentionally does not authorize signatures/scripts.
    Returns the fee in atomic units.
    """
    input_value, output_value = validate_transaction(tx, utxos)
    created = [OutPoint(tx.txid, i) for i in range(len(tx.outputs))]
    if any(outpoint in utxos for outpoint in created):
        raise ValueError("transaction would overwrite an existing UTXO")
    for txin in tx.inputs:
        del utxos[txin.previous_output]
    for outpoint, output in zip(created, tx.outputs):
        utxos[outpoint] = output
    return input_value - output_value
