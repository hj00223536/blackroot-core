#!/usr/bin/env python3
"""Run the test suite with ResourceWarning tracing and print SQLite leak sites."""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    env = os.environ.copy()
    env["PYTHONTRACEMALLOC"] = "10"
    command = [
        sys.executable,
        "-X",
        "tracemalloc=10",
        "-W",
        "always::ResourceWarning",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-v",
    ]
    result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout
    sys.stdout.write(output)
    warning_lines = [
        line for line in output.splitlines()
        if "ResourceWarning" in line or "allocated at" in line or "Object allocated at" in line
    ]
    print("\\n=== SQLITE RESOURCE WARNING SUMMARY ===")
    if warning_lines:
        print("\\n".join(warning_lines))
    else:
        print("No ResourceWarning lines captured.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
