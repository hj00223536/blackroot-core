"""Block structure and transaction-accounting validation prototype.

This module checks transaction ordering, merkle commitment, duplicate txids,
UTXO value conservation, and the coinbase reward ceiling. It deliberately does
NOT execute scripts, verify signatures, enforce coinbase maturity, or validate
header difficulty/timestamps. It is not production consensus.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blackroot_consensus import block_subsidy, MAX_MONEY
from .blackroot_chain import BlockHeader
from .blackroot_transactions import (
    OutPoint,
    Transaction,
    TxOutput,
    apply_transaction,
    merkle_root,
)

COINBASE_INDEX = 0xFFFFFFFF
ZERO_TXID = bytes(32)
MAX_BLOCK_TRANSACTIONS = 100_000


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


def _output_total(outputs: tuple[TxOutput, ...]) -> int:
    total = 0
    for output in outputs:
        output.serialize()
        total += output.value
        if total > MAX_MONEY:
            raise ValueError("transaction output total exceeds money range")
    return total


def validate_block_transactions(
    block: Block,
    parent_utxos: dict[OutPoint, TxOutput],
    height: int,
) -> tuple[dict[OutPoint, TxOutput], int]:
    """Validate block transaction accounting against a parent UTXO snapshot.

    Returns (new UTXO snapshot, total_fees). The input mapping is not mutated.
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

    working = dict(parent_utxos)
    fees = 0
    for tx in block.transactions[1:]:
        fee = apply_transaction(tx, working)
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
