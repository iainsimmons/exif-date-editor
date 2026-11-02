import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from PIL import Image

from exif_utils import (
    EXIFTOOL,
    apply_offset,
    parse_offset,
    read_metadata,
    set_alldates,
    set_date_keep_time,
    set_metadata,
)
from file_model import normalize_path


def exiftool_available() -> bool:
    return Path(EXIFTOOL).exists() or shutil.which(EXIFTOOL) is not None


class OffsetParsingTests(unittest.TestCase):
    def test_positive_units(self):
        self.assertEqual(parse_offset("+2d3h"), timedelta(days=2, hours=3))
        self.assertEqual(parse_offset("15m"), timedelta(minutes=15))
        self.assertEqual(parse_offset("+30s"), timedelta(seconds=30))

    def test_negative_units(self):
        self.assertEqual(parse_offset("-1d"), timedelta(days=-1))
        self.assertEqual(parse_offset("-2h30m"), timedelta(hours=-2, minutes=-30))

    def test_zero(self):
        self.assertEqual(parse_offset("0d"), timedelta(0))

    def test_invalid(self):
        for value in ("", "abc", "1x", "1d2", "+", "-"):
            with self.assertRaises(ValueError):
                parse_offset(value)


class ValidationTests(unittest.TestCase):
    def test_set_alldates_rejects_bad_input(self):
        ok, message = set_alldates(["/tmp/none.jpg"], "2020-01-01 00:00:00")
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_set_alldates_rejects_empty(self):
        ok, message = set_alldates(["/tmp/none.jpg"], "")
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_set_metadata_rejects_unsupported_tag(self):
        ok, message = set_metadata(["/tmp/none.jpg"], {"LensModel": "x"})
        self.assertFalse(ok)
        self.assertIn("Unsupported", message)

    def test_set_metadata_rejects_empty_fields(self):
        ok, message = set_metadata(["/tmp/none.jpg"], {})
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_read_metadata_empty(self):
        self.assertEqual(read_metadata([]), {})


@unittest.skipUnless(exiftool_available(), "exiftool not available")
class ExifWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.photo = os.path.join(self.temp_dir.name, "photo.jpg")
        Image.new("RGB", (32, 32), (120, 30, 200)).save(self.photo, "JPEG")
        self.key = normalize_path(self.photo)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _metadata(self):
        return read_metadata([self.photo]).get(self.key, {})

    def test_set_alldates_roundtrip(self):
        ok, message = set_alldates([self.photo], "2020:01:02 03:04:05")
        self.assertTrue(ok, message)
        metadata = self._metadata()
        self.assertEqual(metadata.get("DateTimeOriginal"), "2020:01:02 03:04:05")
        self.assertEqual(metadata.get("CreateDate"), "2020:01:02 03:04:05")
        self.assertEqual(metadata.get("ModifyDate"), "2020:01:02 03:04:05")

    def test_apply_offset(self):
        ok, message = set_alldates([self.photo], "2020:01:02 03:04:05")
        self.assertTrue(ok, message)
        ok, message = apply_offset([self.photo], "+1d2h")
        self.assertTrue(ok, message)
        self.assertEqual(self._metadata().get("DateTimeOriginal"), "2020:01:03 05:04:05")

    def test_apply_offset_without_date(self):
        ok, message = apply_offset([self.photo], "+1d")
        self.assertFalse(ok)
        self.assertIn("no date", message)

    def test_set_date_keep_time(self):
        ok, message = set_alldates([self.photo], "2020:01:02 03:04:05")
        self.assertTrue(ok, message)
        ok, message = set_date_keep_time([self.photo], "2021-05-06")
        self.assertTrue(ok, message)
        self.assertEqual(self._metadata().get("DateTimeOriginal"), "2021:05:06 03:04:05")

    def test_set_date_keep_time_invalid_date(self):
        ok, message = set_date_keep_time([self.photo], "2021-13-40")
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_set_metadata_roundtrip_and_clear(self):
        fields = {
            "OwnerName": "Alice",
            "Artist": "Bob",
            "Copyright": "Copyright 2026",
            "ImageDescription": "Test image",
        }
        ok, message = set_metadata([self.photo], fields)
        self.assertTrue(ok, message)
        metadata = self._metadata()
        for tag, value in fields.items():
            self.assertEqual(metadata.get(tag), value)

        ok, message = set_metadata([self.photo], {"OwnerName": None})
        self.assertTrue(ok, message)
        self.assertNotIn("OwnerName", self._metadata())

    def test_read_metadata_duplicate_paths(self):
        ok, message = set_alldates([self.photo], "2020:01:02 03:04:05")
        self.assertTrue(ok, message)
        result = read_metadata([self.photo, self.photo])
        self.assertEqual(len(result), 1)
        self.assertIn(self.key, result)


if __name__ == "__main__":
    unittest.main()
