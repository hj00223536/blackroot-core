"""Block transaction validation with fail-closed legacy P2PKH authorization.

This module checks transaction ordering, merkle commitment, duplicate txids,
P2PKH signatures, UTXO value conservation, and the coinbase reward ceiling.
It is still not production consensus: coinbase maturity, complete Script,
header PoW/difficulty/future-time and other rules remain incomplete; relative sequence locks (BIP68) and full Script are not implemented.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .blackroot_consensus import block_subsidy, MAX_MONEY
from .blackroot_maturity import UTXOProvenance, validate_coinbase_maturity
from .blackroot_chain import BlockHeader
from .blackroot_script import validate_transaction_scripts
from .blackroot_transactions import (
    OutPoint,
    Transaction,
    TxOutput,
    apply_transaction,
    merkle_root,
    compact_size,
    _read_compact_size,
    _deserialize_transaction_from,
)

COINBASE_INDEX = 0xFFFFFFFF
ZERO_TXID = bytes(32)
MAX_BLOCK_TRANSACTIONS = 100_000
# Provisional legacy-block byte ceiling; finalize only with protocol test vectors.
MAX_BLOCK_SIZE = 1_000_000


def is_coinbase(tx: Transaction) -> bool:
    """Recognize the single-input null-prevout coinbase form."""
    return (
        isinstance(tx, Transaction)
        and len(tx.inputs) == 1
        and tx.inputs[0].previous_output == OutPoint(ZERO_TXID, COINBASE_INDEX)
    )


@dataclass(frozen=True)
class Block:
    header: BlockHeader
    transactions: tuple[Transaction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.header, BlockHeader):
            raise TypeError("header must be a BlockHeader")
        if not isinstance(self.transactions, tuple):
            raise TypeError("transactions must be a tuple")
        if not 1 <= len(self.transactions) <= MAX_BLOCK_TRANSACTIONS:
            raise ValueError("block must contain a supported transaction count")
        if not all(isinstance(tx, Transaction) for tx in self.transactions):
            raise TypeError("all block entries must be transactions")

        if self.serialized_size > MAX_BLOCK_SIZE:
            raise ValueError("serialized block exceeds provisional size limit")

    def serialize(self) -> bytes:
        return self.header.serialize() + compact_size(len(self.transactions)) + b"".join(
            tx.serialize() for tx in self.transactions
        )

    @classmethod
    def deserialize(cls, raw: bytes) -> "Block":
        """Parse a complete legacy block and reject malformed or trailing data."""
        if not isinstance(raw, bytes):
            raise TypeError("serialized block must be bytes")
        if len(raw) < 81:
            raise ValueError("truncated block header or transaction count")
        if len(raw) > MAX_BLOCK_SIZE:
            raise ValueError("serialized block exceeds provisional size limit")
        version, prev_hash, root, timestamp, bits, nonce = struct.unpack("<i32s32sIII", raw[:80])
        header = BlockHeader(version, prev_hash, root, timestamp, bits, nonce)
        count, offset = _read_compact_size(raw, 80)
        if not 1 <= count <= MAX_BLOCK_TRANSACTIONS:
            raise ValueError("unsupported block transaction count")
        transactions = []
        for _ in range(count):
            tx, offset = _deserialize_transaction_from(raw, offset)
            transactions.append(tx)
        if offset != len(raw):
            raise ValueError("trailing bytes after serialized block")
        return cls(header, tuple(transactions))

    @property
    def serialized_size(self) -> int:
        """Return legacy serialized header, transaction count, and body size."""
        return 80 + len(compact_size(len(self.transactions))) + sum(
            len(tx.serialize()) for tx in self.transactions
        )


def _output_total(outputs: tuple[TxOutput, ...]) -> int:
    total = 0
    for output in outputs:
        output.serialize()
        total += output.value
        if total > MAX_MONEY:
            raise ValueError("transaction output total exceeds money range")
    return total


LOCKTIME_THRESHOLD = 500_000_000


def is_final_transaction(tx: Transaction, height: int, median_time_past: int | None) -> bool:
    """Evaluate legacy absolute nLockTime finality for a candidate block.

    Timestamp locks use parent-chain median-time-past. Relative sequence
    locks (BIP68) are not implemented.
    """
    if tx.lock_time == 0:
        return True
    if tx.lock_time < LOCKTIME_THRESHOLD:
        comparison = height
    else:
        if median_time_past is None:
            raise ValueError("median-time-past is required for timestamp nLockTime")
        if not isinstance(median_time_past, int) or isinstance(median_time_past, bool) or median_time_past < 0:
            raise ValueError("median-time-past must be a non-negative integer")
        comparison = median_time_past
    if tx.lock_time < comparison:
        return True
    return all(txin.sequence == 0xFFFFFFFF for txin in tx.inputs)


SEQUENCE_LOCKTIME_DISABLE_FLAG = 1 << 31
SEQUENCE_LOCKTIME_TYPE_FLAG = 1 << 22
SEQUENCE_LOCKTIME_MASK = 0x0000FFFF


def validate_relative_sequence_locks(
    tx: Transaction,
    parent_provenance: dict[OutPoint, UTXOProvenance] | None,
    candidate_height: int,
) -> None:
    """Enforce BIP68 height-based relative locks; reject unsupported time locks.

    BIP68 applies only to version >= 2. Inputs with the disable flag are
    ignored. Timestamp-based relative locks are rejected until UTXO creation
    MTP is authenticated and persisted.
    """
    if tx.version < 2:
        return
    for txin in tx.inputs:
        sequence = txin.sequence
        if sequence & SEQUENCE_LOCKTIME_DISABLE_FLAG:
            continue
        if sequence & SEQUENCE_LOCKTIME_TYPE_FLAG:
            raise ValueError("time-based relative sequence locks are not supported")
        if parent_provenance is None:
            raise ValueError("authenticated UTXO provenance is required for relative sequence locks")
        provenance = parent_provenance.get(txin.previous_output)
        if provenance is None:
            raise ValueError("missing authenticated UTXO provenance for relative sequence lock")
        relative_blocks = sequence & SEQUENCE_LOCKTIME_MASK
        minimum_height = provenance.created_height + relative_blocks
        if candidate_height < minimum_height:
            raise ValueError("transaction violates relative height sequence lock")


def validate_block_transactions(
    block: Block,
    parent_utxos: dict[OutPoint, TxOutput],
    height: int,
    parent_provenance: dict[OutPoint, UTXOProvenance] | None = None,
    median_time_past: int | None = None,
) -> tuple[dict[OutPoint, TxOutput], int]:
    """Validate block transactions against a parent UTXO snapshot.

    When parent_provenance is supplied it must cover every parent UTXO and
    coinbase maturity is enforced. Callers without authenticated provenance
    retain the legacy accounting-only behavior and MUST NOT use it for chain
    state transitions. Returns (new UTXO snapshot, total_fees).
    Coinbase outputs are added only after regular transactions are processed,
    preventing same-block spending of the current block's coinbase.
    """
    if not isinstance(block, Block):
        raise TypeError("block must be a Block")
    if not isinstance(parent_utxos, dict):
        raise TypeError("parent_utxos must be a dict")
    if not isinstance(height, int) or isinstance(height, bool) or height < 0:
        raise ValueError("height must be a non-negative integer")

    coinbase = block.transactions[0]
    if not is_coinbase(coinbase):
        raise ValueError("first transaction must be coinbase")
    if len(coinbase.inputs[0].script_sig) < 2 or len(coinbase.inputs[0].script_sig) > 100:
        raise ValueError("coinbase script_sig length must be between 2 and 100 bytes")
    if any(is_coinbase(tx) for tx in block.transactions[1:]):
        raise ValueError("block contains more than one coinbase transaction")

    txids = [tx.txid for tx in block.transactions]
    if len(set(txids)) != len(txids):
        raise ValueError("block contains duplicate transaction ids")
    if merkle_root(txids) != block.header.merkle_root:
        raise ValueError("block merkle root does not match transactions")

    if parent_provenance is not None:
        if not isinstance(parent_provenance, dict):
            raise TypeError("parent_provenance must be a dict")
        if set(parent_provenance) != set(parent_utxos):
            raise ValueError("complete authenticated UTXO provenance is required")
        for provenance in parent_provenance.values():
            if not isinstance(provenance, UTXOProvenance):
                raise TypeError("invalid UTXO provenance entry")

    working = dict(parent_utxos)
    working_provenance = None if parent_provenance is None else dict(parent_provenance)
    fees = 0
    for tx in block.transactions[1:]:
        if not is_final_transaction(tx, height, median_time_past):
            raise ValueError("transaction is non-final for candidate block height/time")
        validate_relative_sequence_locks(tx, working_provenance, height)
        if parent_provenance is not None:
            for txin in tx.inputs:
                provenance = working_provenance.get(txin.previous_output)
                if provenance is not None:
                    validate_coinbase_maturity(provenance, height)
        # Authorization is consensus-critical: reject unsupported or invalid scripts.
        validate_transaction_scripts(tx, working)
        fee = apply_transaction(tx, working)
        if working_provenance is not None:
            for txin in tx.inputs:
                working_provenance.pop(txin.previous_output, None)
            for index, _output in enumerate(tx.outputs):
                working_provenance[OutPoint(tx.txid, index)] = UTXOProvenance(height, False)
        fees += fee
        if fees > MAX_MONEY:
            raise ValueError("total block fees exceed money range")

    coinbase_value = _output_total(coinbase.outputs)
    allowed = block_subsidy(height) + fees
    if coinbase_value > allowed:
        raise ValueError("coinbase reward exceeds subsidy plus transaction fees")

    for index, output in enumerate(coinbase.outputs):
        outpoint = OutPoint(coinbase.txid, index)
        if outpoint in working:
            raise ValueError("coinbase would overwrite an existing UTXO")
        working[outpoint] = output
    return working, fees
