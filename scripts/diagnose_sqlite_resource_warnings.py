#!/usr/bin/env python3
"""Run tests with live output and SQLite ResourceWarning tracing."""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    env = os.environ.copy()
    env["PYTHONTRACEMALLOC"] = "10"
    command = [
        sys.executable,
        "-X", "tracemalloc=10",
        "-W", "always::ResourceWarning",
        "-m", "unittest", "discover",
        "-s", "tests", "-v",
    ]

    print("=== STARTING TEST SUITE ===", flush=True)
    result = subprocess.run(
        command,
        env=env,
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print("\n=== SQLITE RESOURCE WARNING CHECK ===", flush=True)
    print(f"Test process exit code: {result.returncode}", flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
