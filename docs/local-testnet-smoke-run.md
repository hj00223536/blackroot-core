# BLACKROOT isolated local Testnet smoke run

**Status: local-only engineering exercise. This is not a public Testnet launch.**

The two example files in `examples/` use the documented genesis *candidate* and
a local fixture message magic. Neither the genesis candidate nor the network
identity/magic has been approved as a permanent network constant. Do not reuse
these settings for a public network, wallet, mining pool, exchange, or real
funds. Test coins have no value.

## Requirements

- Python 3.10 or newer.
- A checkout of this repository at the same commit for both processes.
- Two separate data directories.

## Start node A

From the repository root, in terminal 1:

```sh
python -m src.blackroot_node \
  --config examples/testnet-local-node-a.json \
  --data-dir ./data/local-node-a \
  --bind-host 127.0.0.1
```

## Start node B

In terminal 2:

```sh
python -m src.blackroot_node \
  --config examples/testnet-local-node-b.json \
  --data-dir ./data/local-node-b \
  --bind-host 127.0.0.1 \
  --connect 127.0.0.1:18444
```

Each process should print a JSON `node_started` record. Node B should report
one connected peer after its version/verack handshake. Both records should
show the same genesis hash and initial best-chain hash. Stop each process with
Ctrl-C; each process closes its runtime and SQLite state.

## What this demonstrates

- Strict JSON parsing and validation of the same explicit candidate genesis.
- Two separate SQLite data directories.
- Loopback-only TCP listener and outbound peer connection.
- Version/verack handshake and the current header-sync startup path.
- Graceful Ctrl-C shutdown.

## What this does not demonstrate

This smoke run does **not** establish full block-body synchronization, complete
consensus validation, a working wallet or miner, peer discovery, public
network security, stable chain parameters, or economic value. The CLI
intentionally rejects non-loopback addresses. Do not open router ports or
change the bind host to a public interface.

The next release gate remains a reviewed normative Testnet specification,
independent client reproduction, complete block/transaction consensus,
adversarial multi-process testing, and public operational/security review.
