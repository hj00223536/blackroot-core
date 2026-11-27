# Node Entry-Point Lock Audit

**Status: BOUNDED SOURCE AUDIT — NOT A PRODUCTION READINESS APPROVAL**

## Scope inspected

- `src/blackroot_node.py`: the only discovered executable node CLI module with a `main()` entry point.
- `pyproject.toml`: defines the package and dependencies but no console-script entry point.
- `src/blackroot_node_runtime.py`: embeddable lifecycle wrapper; it accepts a caller-provided `PersistentNodeState`.
- `src/blackroot_p2p_node_service.py` and `src/blackroot_p2p_service.py`: service components, not standalone process entry points.
- Repository tree under `scripts/` and `examples/`: contains verification utilities and local testnet JSON examples; no additional node daemon launcher was identified.

## Verified change

The CLI now calls `PersistentNodeState.open_locked(data_dir, data_dir / "blackroot-node.sqlite", ...)`. The state object owns the data-directory lock, and `PersistentNodeState.close()` releases it after coordinated storage shutdown. The CLI subprocess test already exercises rejection of a second process opening the same data directory.

## Remaining bypass and limitation

This is not a repository-wide mandatory-lock guarantee:

- `PersistentNodeState.__init__()` remains a compatibility constructor without a process lock.
- `PersistentNodeState.open_coordinated()` still opens coordinated SQLite state without a process lock.
- `BlackrootNodeRuntime` accepts a caller-supplied state and does not itself require that the state owns a data-directory lock.
- The P2P service modules can be embedded by another application; the CLI audit does not govern external embedding code.

These APIs are used by tests and compatibility workflows. They were not removed or silently redefined in this change. A future production node composition root must require a locked state (or a separately reviewed equivalent ownership primitive) and must not expose an unlocked production startup path.

## Gate decision

**The mandatory process-ownership gate remains OPEN.** The local CLI path is migrated, but the reusable runtime boundary is not lock-enforcing, and no production Mainnet composition root exists. Do not describe this as a production daemon, public testnet, or Mainnet-ready implementation.

Before closing this gate:
1. Define the supported production composition root and its lifecycle contract.
2. Make lock ownership mandatory at that boundary, including startup failure and shutdown behavior.
3. Add integration tests proving unlocked state is rejected by the production composition root and competing processes cannot share the data directory.
4. Review directory permissions, symlink/path alias behavior, filesystem semantics, crash recovery, and backup/restore interactions.
5. Run and pass the complete CI matrix on the exact resulting commit.
