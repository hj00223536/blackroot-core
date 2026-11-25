# P2P headers message codec

`src/blackroot_p2p_headers.py` implements a bounded Bitcoin-style headers
payload codec: a canonical CompactSize count followed by up to 2,000 entries.
Each entry contains an 80-byte header and a zero transaction-count byte.

The decoder rejects truncated entries, trailing bytes, non-canonical counts,
non-zero transaction counts, and counts above the configured limit.

This is serialization only. It does not prove proof-of-work, check ancestry,
validate difficulty or timestamps, select a best chain, request block bodies,
or validate transactions. Decoded headers must be passed through the chain's
consensus validation; decoded data is untrusted until then.
