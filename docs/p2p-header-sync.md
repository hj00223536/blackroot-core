# Applying peer headers to the chain

`accept_headers_payload` decodes a bounded headers message and passes its
headers to `HeaderChain.add_batch`. The batch uses the chain's proof-of-work,
parent linkage, target/difficulty, and median-time-past checks. A network-adjusted
future-time limit can be supplied by the caller.

Batch insertion is atomic in memory: if any header fails, the DAG nodes and
selected tip are restored to their pre-call state.

This is not a complete synchronization client. There is no socket transport,
peer scoring, getheaders locator generation, getdata/block-body scheduling,
persistent peer state, or full production consensus. Headers are not blocks;
full block and transaction validation remains mandatory.
