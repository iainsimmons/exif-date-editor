import os
import tempfile
import unittest
from pathlib import Path

from config import Config, MAX_RECENT_DIRS, default_picker_dir


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "config.json"
        self.config = Config(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_defaults(self):
        self.assertEqual(self.config.get("sort_field"), "name")
        self.assertEqual(self.config.get("view_mode"), "grid")
        self.assertTrue(self.config.get("group_raw_jpg"))
        self.assertEqual(self.config.recent_dirs(), [])

    def test_set_persists(self):
        self.config.set("sort_field", "date")
        self.config.set("sort_reverse", True)
        reloaded = Config(self.path)
        self.assertEqual(reloaded.get("sort_field"), "date")
        self.assertTrue(reloaded.get("sort_reverse"))

    def test_recents_dedupe_and_cap(self):
        directories = []
        for index in range(MAX_RECENT_DIRS + 2):
            directory = os.path.join(self.temp_dir.name, f"dir{index}")
            os.makedirs(directory)
            directories.append(directory)
        for directory in directories:
            self.config.add_recent_dir(directory)
        recents = self.config.recent_dirs()
        self.assertEqual(len(recents), MAX_RECENT_DIRS)
        self.assertEqual(recents[0], str(Path(directories[-1]).resolve()))
        self.assertEqual(len(set(recents)), MAX_RECENT_DIRS)

        repeated = directories[3]
        self.config.add_recent_dir(repeated)
        recents = self.config.recent_dirs()
        self.assertEqual(recents[0], str(Path(repeated).resolve()))
        self.assertEqual(recents.count(str(Path(repeated).resolve())), 1)
        self.assertEqual(len(recents), MAX_RECENT_DIRS)
        self.assertEqual(self.config.picker_dir(), str(Path(repeated).resolve()))

    def test_clear_recents(self):
        directory = os.path.join(self.temp_dir.name, "photos")
        os.makedirs(directory)
        self.config.add_recent_dir(directory)
        self.assertEqual(len(self.config.recent_dirs()), 1)
        self.config.clear_recent_dirs()
        self.assertEqual(self.config.recent_dirs(), [])

    def test_remember_picker_dir(self):
        directory = os.path.join(self.temp_dir.name, "picker")
        os.makedirs(directory)
        self.config.remember_picker_dir(directory)
        self.assertEqual(self.config.picker_dir(), str(Path(directory).resolve()))

    def test_default_picker_dir_uses_valid_directory(self):
        self.assertEqual(
            default_picker_dir(self.temp_dir.name), str(Path(self.temp_dir.name).resolve())
        )
        fallback = default_picker_dir()
        self.assertTrue(os.path.isdir(fallback))


if __name__ == "__main__":
    unittest.main()
