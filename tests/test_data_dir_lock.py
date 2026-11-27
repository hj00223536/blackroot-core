import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.blackroot_data_dir_lock import DataDirectoryLock


class DataDirectoryLockTests(unittest.TestCase):
    def test_exclusive_lock_rejects_second_owner_and_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DataDirectoryLock(directory).acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "another BLACKROOT node"):
                    DataDirectoryLock(directory).acquire()
                self.assertTrue(first.path.exists())
                self.assertEqual(first.path.read_text(), f"pid={os.getpid()}\n")
            finally:
                first.release()
            with DataDirectoryLock(directory):
                pass

    def test_rejects_symbolic_link_at_lock_path(self):
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("platform does not expose O_NOFOLLOW")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "unrelated-file"
            target.write_text("do not modify")
            lock_path = root / ".blackroot-node.lock"
            lock_path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "must not be a symbolic link"):
                DataDirectoryLock(root).acquire()
            self.assertEqual(target.read_text(), "do not modify")

    def test_new_data_directory_is_created_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "nested" / "node-data"
            lock = DataDirectoryLock(root).acquire()
            try:
                self.assertTrue(lock.is_held)
                self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
                self.assertTrue((root / ".blackroot-node.lock").is_file())
            finally:
                lock.release()

    def test_rejects_group_or_world_accessible_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "node-data"
            root.mkdir(mode=0o700)
            root.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, "permissions must exclude group and other"):
                DataDirectoryLock(root).acquire()
            self.assertFalse((root / ".blackroot-node.lock").exists())

    def test_rejects_non_regular_file_at_lock_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / ".blackroot-node.lock"
            lock_path.mkdir()
            with self.assertRaisesRegex(RuntimeError, "must be a regular file"):
                DataDirectoryLock(root).acquire()

    def test_rejects_hard_linked_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside-lock"
            target.write_text("do not modify")
            lock_path = root / ".blackroot-node.lock"
            try:
                lock_path.hardlink_to(target)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"hard links are unsupported: {exc}")
            with self.assertRaisesRegex(RuntimeError, "hard-link aliases"):
                DataDirectoryLock(root).acquire()
            self.assertEqual(target.read_text(), "do not modify")

    def test_rejects_group_or_world_accessible_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / ".blackroot-node.lock"
            lock_path.write_text("existing lock")
            lock_path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "permissions must exclude group and other"):
                DataDirectoryLock(root).acquire()
            self.assertEqual(lock_path.read_text(), "existing lock")

    def test_kernel_releases_lock_after_owner_process_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            child_code = (
                "import sys, time; "
                "from src.blackroot_data_dir_lock import DataDirectoryLock; "
                "lock=DataDirectoryLock(sys.argv[1]).acquire(); "
                "print('LOCKED', flush=True); time.sleep(30)"
            )
            env = os.environ.copy()
            root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
            child = subprocess.Popen(
                [sys.executable, "-c", child_code, directory],
                cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "LOCKED")
                with self.assertRaisesRegex(RuntimeError, "another BLACKROOT node"):
                    DataDirectoryLock(directory).acquire()
                child.kill()
                child.communicate(timeout=5)
                with DataDirectoryLock(directory):
                    pass
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
