# Persistent block connection prototype

The SQLite UTXO store now has block-index and ordered block-transaction tables.
Its `connect_block(block, height)` method performs the following in one SQLite
write transaction:

1. Enforces a sequential height and exact parent hash (first block is height 0
   with a zero previous hash).
2. Loads the current UTXO set and runs the existing block transaction-accounting
   validator.
3. Stores the block header, block hash, transaction count, fees, and serialized
   transactions in order.
4. Replaces the UTXO snapshot with the validated result.
5. Rolls back all writes if any validation or database operation fails.

The `tip()` method returns the stored height and hash. The tests cover
persistence after reopening, invalid height, invalid parent, and rollback on
coinbase overpayment.

## Important limitations

This is not a complete chain database or production consensus implementation.
It does not validate proof of work, difficulty transitions, timestamps,
script execution, signatures, coinbase maturity, block size/weight, or
transaction finality. It supports only direct extension of one stored chain;
there are no side branches, undo records, or reorganization support. The
first block's UTXO state is not a real generated genesis distribution.


## Tip disconnection and undo records

The prototype now records two undo tables atomically with each connected block: `block_undo_spent` stores parent-state outputs spent by regular transactions, and `block_undo_created` records every output created by the block. The `disconnect_tip(expected_tip_hash)` operation requires an exact tip hash, removes outputs created by that block, restores only outputs that existed in the parent UTXO snapshot, and deletes the block row (cascading its transactions and undo records) in one SQLite transaction.

Tests cover restoring a spent parent output, removing block-created outputs, wrong-hash rejection, empty-chain rejection, and cleanup of genesis undo data.

This is only a **single-tip storage rollback primitive**. It is not full chain reorganization: there is no side-branch index, competing-chain selection, validated cumulative work, or automatic disconnect/connect orchestration. The caller must not use it to accept an unvalidated replacement branch. Script and signature verification, proof-of-work/header validation, coinbase maturity, and other consensus rules remain absent.


## Atomic active-chain suffix replacement

The store now exposes `reorganize(disconnect_hashes, connect_blocks)`. The
disconnect list must name the current active suffix in tip-first order; the
replacement blocks must be ordered fork-first. In one SQLite write transaction
the method restores spent parent outputs, removes disconnected outputs and
records, validates each replacement block's transaction accounting against
the evolving UTXO set, writes its block/transaction/undo records, and advances
the stored tip. If any replacement block fails validation or any database
operation fails, the entire operation—including all disconnects—is rolled
back.

Tests cover a successful one-block replacement, preservation of the common
ancestor's UTXO, removal of the old branch output, rejection of incorrect
disconnect order, and rollback when a replacement overpays its coinbase.

**Critical boundary:** this method is a transactional storage primitive, not
an autonomous consensus reorganization engine. It does not decide whether the
replacement has greater chainwork and does not validate header PoW, difficulty,
timestamps, scripts/signatures, coinbase maturity, or branch-specific full
consensus. A caller must establish all those conditions before calling it.
