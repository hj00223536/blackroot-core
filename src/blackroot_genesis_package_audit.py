"""Fail-closed in-memory artifact inventory for proposed Genesis review packages.

This validates package membership, byte limits and externally pinned SHA-256
digests only. It does not parse artifacts, authenticate their authors, verify
signatures, or authorize activation.
"""
from __future__ import annotations

import hashlib
from types import MappingProxyType
from typing import Mapping

_REQUIRED = frozenset({"manifest.json", "approval.json", "trust-anchors.json", "verification-report.md", "release-approval.md"})
_OPTIONAL = frozenset({"checksums.txt"})
_MAX_FILE_BYTES = 2_000_000
_MAX_TOTAL_BYTES = 5_000_000


def audit_genesis_package_inventory(
    artifacts: Mapping[str, bytes],
    *,
    expected_sha256: Mapping[str, str],
) -> Mapping[str, str]:
    """Return immutable SHA-256 inventory after strict membership/pin checks.

    expected_sha256 must be supplied by an independent review channel. A
    checksum in the package itself is not an independent pin.
    """
    if not isinstance(artifacts, Mapping) or not isinstance(expected_sha256, Mapping):
        raise TypeError("artifacts and expected_sha256 must be mappings")
    names = set(artifacts)
    missing = _REQUIRED - names
    unexpected = names - _REQUIRED - _OPTIONAL
    if missing:
        raise ValueError(f"missing required package artifacts: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"unexpected package artifacts: {sorted(unexpected)}")
    if set(expected_sha256) != names:
        raise ValueError("external digest pins must name exactly the supplied artifacts")
    total = 0
    result: dict[str, str] = {}
    for name in sorted(names):
        if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("artifact names must be simple file names")
        data = artifacts[name]
        if not isinstance(data, bytes):
            raise TypeError(f"{name} must be supplied as bytes")
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError(f"{name} exceeds per-file size limit")
        total += len(data)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("package exceeds total size limit")
        pin = expected_sha256[name]
        if (not isinstance(pin, str) or len(pin) != 64
                or any(c not in "0123456789abcdef" for c in pin)):
            raise ValueError(f"{name} external SHA-256 pin is malformed")
        actual = hashlib.sha256(data).hexdigest()
        if actual != pin:
            raise ValueError(f"{name} does not match its external SHA-256 pin")
        result[name] = actual
    return MappingProxyType(result)
