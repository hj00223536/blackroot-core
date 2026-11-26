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
