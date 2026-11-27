"""Advisory process lock for a BLACKROOT node data directory.

The kernel releases flock ownership when the process exits, including abrupt
process termination. The lock file is intentionally persistent: unlinking it
while another process may have it open can create split-lock races.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


class DataDirectoryLock:
    """Hold an exclusive POSIX advisory lock for one resolved data directory."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.path = self.data_dir / ".blackroot-node.lock"
        self._fd: int | None = None
        self._dir_fd: int | None = None

    def acquire(self) -> "DataDirectoryLock":
        if self._fd is not None:
            raise RuntimeError("data-directory lock is already held")
        try:
            import fcntl
        except ImportError as exc:
            raise RuntimeError(
                "this platform does not provide POSIX flock; refusing unsafe node startup"
            ) from exc

        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        # Pin the directory inode, then open the lock relative to that descriptor.
        dir_fd = os.open(self.data_dir, directory_flags)
        try:
            directory_stat = os.fstat(dir_fd)
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise RuntimeError("data directory must be a directory")
            if hasattr(os, "getuid") and directory_stat.st_uid != os.getuid():
                raise RuntimeError("data directory must be owned by the current user")
            if stat.S_IMODE(directory_stat.st_mode) & 0o077:
                raise RuntimeError(
                    "data directory permissions must exclude group and other access (mode 0700 or stricter)"
                )
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(".blackroot-node.lock", flags, 0o600, dir_fd=dir_fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise RuntimeError("data-directory lock path must not be a symbolic link") from exc
                if exc.errno == errno.EISDIR:
                    raise RuntimeError("data-directory lock path must be a regular file") from exc
                raise
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                raise RuntimeError("data-directory lock path must be a regular file")
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError(f"another BLACKROOT node already holds data directory: {self.data_dir}") from exc
                os.ftruncate(fd, 0)
                os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
                os.fsync(fd)
            except BaseException:
                os.close(fd)
                raise
        except BaseException:
            os.close(dir_fd)
            raise
        self._dir_fd = dir_fd
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
            dir_fd, self._dir_fd = self._dir_fd, None
            if dir_fd is not None:
                os.close(dir_fd)

    def __enter__(self) -> "DataDirectoryLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

    @property
    def is_held(self) -> bool:
        """Whether this instance currently owns its advisory process lock."""
        return self._fd is not None
