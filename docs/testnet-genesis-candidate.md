# BLACKROOT Testnet v1 genesis candidate

**Status: candidate vector for review only — not an activated network constant.**

This vector is a deterministic engineering exercise to test the repository's existing legacy transaction/header encoders. It does not activate a testnet, define a complete protocol, or authorize public peers or mining. Do not use it for mainnet.

## Candidate parameters

| Field | Candidate |
|---|---|
| Network label | BLACKROOT Testnet v1 candidate |
| Genesis timestamp | 2026-11-25 00:00:00 UTC |
| Timestamp integer | `1795564800` |
| Header version | `1` |
| Previous hash | 32 zero bytes |
| Initial compact target | `0x207fffff` |
| Nonce | `0` |
| Coinbase transaction version | `1` |
| Coinbase input | null outpoint; index `0xffffffff` |
| Coinbase scriptSig | `0101` |
| Coinbase output | zero atomic units; scriptPubKey `6a` (OP_RETURN) |
| Lock time | `0` |

The deliberately easy target is suitable only for deterministic local test-vector checking. It is not a secure public-network mining target.

## Exact serialized transaction

Length: 63 bytes.

```text
01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff020101ffffffff010000000000000000016a00000000
```

Transaction ID (display byte order):

```text
35993aaf3055dd3e72466a4724bf6a0c4d1ff340130266b3a1c71b100490a42e
```

## Exact 80-byte header

```text
0100000000000000000000000000000000000000000000000000000000000000000000002ea49004101bc7a1b366021340f31f4d0c6abf24476a46723edd5530af3a99350025066bffff7f2000000000
```

Genesis block hash (display byte order):

```text
12d0a70715fcc771e2228e8a8e2f85b4ada2b1bf2991c2a564553c0b9c922269
```

The candidate transaction has a zero-value OP_RETURN output and does not allocate spendable genesis coins.

## Required review before activation

- [ ] Independently reproduce the transaction bytes, txid, merkle root, header bytes, and block hash in a second implementation.
- [ ] Review the timestamp and coinbase message convention.
- [ ] Freeze a unique chain identifier and P2P message-start bytes, address prefixes, ports, and protocol version.
- [ ] Specify every genesis and subsequent-block consensus rule, including retarget boundary behavior and timestamp policy.
- [ ] Add cross-client test vectors and external consensus/security review.
- [ ] Build a runnable node application and pass a multi-process TCP convergence test using this exact genesis.
- [ ] Publish a versioned specification and explicit testnet reset policy.

Until these checks pass, this vector remains a candidate only. No public Testnet is launched by adding this document.
