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

## Follow-up enforcement change

`PersistentNodeState.data_directory_locked` now reports whether its owned lock is currently held. `BlackrootNodeRuntime(..., require_locked_state=True)` rejects an unlocked state before constructing the P2P sync service. The loopback CLI opts into this enforcement mode. Runtime unit tests were added for both rejection of unlocked state and acceptance/release of a properly locked state. This narrows accidental bypass at the CLI/runtime boundary but does not force every external embedding caller to enable the option; the global production composition-root gate remains open.

## Lock-file path hardening follow-up

The lock acquisition now requests `O_NOFOLLOW` where the platform exposes it, converts symlink-loop rejection into a fail-closed error, rejects directory paths, and verifies the opened lock descriptor is a regular file before attempting `flock`. Regression tests cover a symlink to an unrelated file and a directory at the lock-file path. This reduces lock-path redirection and invalid-file risks; it does not replace restrictive data-directory permissions, protection against privileged local tampering, or filesystem-specific review. CI is pending.


## Data-directory permission enforcement follow-up

The lock now inspects the opened directory descriptor and fails closed unless the
directory is owned by the current process user and has no group/other permission
bits (mode 0700 or stricter). A regression verifies that a 0755 directory is
rejected before the lock file is created. This is a local filesystem hygiene
control; it does not protect against the owning user, root, privileged malware,
unsafe parent-directory replacement, hostile mounts, or rollback of restored
backups. The production storage and backup threat model still requires review.


## SQLite pathname preflight follow-up

The locked state opener now checks the caller-supplied final data-directory
component before resolving it, rejecting a final-component symlink or special
file. It also uses the database basename under the locked directory without
resolving the final database component, then rejects pre-existing database,
WAL, SHM, and rollback-journal paths unless each is a regular file. Tests cover
a symlinked data directory, database file, and WAL sidecar.

These are **preflight checks, not race-free file-descriptor confinement**.
SQLite still opens the database and creates sidecars by pathname after the
checks. Parent path components may be aliases, and a same-UID process or
privileged actor may be able to replace paths or modify the directory. This
change does not establish protection against TOCTOU races, hard-link aliasing,
hostile filesystems/mounts, or privileged tampering. A production-grade
descriptor-relative database-opening design and SQLite WAL compatibility
review remain required before this storage gate can close. No physical
power-loss or device-failure guarantee is inferred from process-crash tests.
