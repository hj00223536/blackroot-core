# Peer address book and admission policy

`PeerAddressBook` adds an in-memory, bounded candidate-address store.
It normalizes endpoints through the parsed IP address, deduplicates by
(IP, port), rejects non-global/non-unicast addresses, rejects stale entries
and timestamps beyond a small future-skew allowance, and enforces a maximum
entry count. Entries can be explicitly pruned by age.

## Important limits

An accepted entry is only a candidate endpoint. It is not authenticated,
verified reachable, or safe to connect to solely because it passed this
basic filter. The book is process-local and non-persistent. It has no
per-source quotas, subnet diversity, reputation, connection success scoring,
DNS resolution policy, or anti-poisoning guarantees. Public address exchange
and automatic dialing remain disabled. Before deployment, add network-specific
allow/deny policy, source quotas, diversity limits, persistence review, and
security testing.
