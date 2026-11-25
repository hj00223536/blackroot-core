"""Advisory process lock for a BLACKROOT node data directory.

The kernel releases flock ownership when the process exits, including abrupt
process termination. The lock file is intentionally persistent: unlinking it
while another process may have it open can create split-lock races.
"""
from __future__ import annotations

import os
from pathlib import Path


class DataDirectoryLock:
    """Hold an exclusive POSIX advisory lock for one resolved data directory."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.path = self.data_dir / ".blackroot-node.lock"
        self._fd: int | None = None

    def acquire(self) -> "DataDirectoryLock":
        if self._fd is not None:
            raise RuntimeError("data-directory lock is already held")
        try:
            import fcntl
        except ImportError as exc:
            raise RuntimeError(
                "this platform does not provide POSIX flock; refusing unsafe node startup"
            ) from exc

        self.data_dir.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        fd = os.open(self.path, flags, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    f"another BLACKROOT node already holds data directory: {self.data_dir}"
                ) from exc
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\\n".encode("ascii"))
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "DataDirectoryLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
