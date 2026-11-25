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
