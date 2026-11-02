import os
import unittest
from datetime import datetime

from file_model import (
    display_date,
    group_date,
    make_groups,
    natural_key,
    normalize_path,
    parse_exif_datetime,
    sort_groups,
)


class NaturalKeyTests(unittest.TestCase):
    def test_natural_ordering(self):
        values = ["IMG10", "IMG2", "img1", "IMG02"]
        ordered = sorted(values, key=natural_key)
        self.assertEqual(ordered, ["img1", "IMG2", "IMG02", "IMG10"])

    def test_equal_numeric_parts(self):
        self.assertEqual(natural_key("IMG02"), natural_key("IMG2"))


class DateParsingTests(unittest.TestCase):
    def test_parse_standard_value(self):
        parsed = parse_exif_datetime("2024:03:05 10:11:12")
        self.assertEqual(parsed, datetime(2024, 3, 5, 10, 11, 12))

    def test_parse_timezone_suffix(self):
        parsed = parse_exif_datetime("2024:03:05 10:11:12+10:00")
        self.assertEqual(parsed, datetime(2024, 3, 5, 10, 11, 12))

    def test_parse_with_space_instead_of_colon(self):
        parsed = parse_exif_datetime("2024:03:05 10:11:12")
        self.assertIsNotNone(parsed)

    def test_invalid_values(self):
        self.assertIsNone(parse_exif_datetime(""))
        self.assertIsNone(parse_exif_datetime("not a date"))
        self.assertIsNone(parse_exif_datetime("2024-03-05 10:11:12"))

    def test_display_date(self):
        self.assertEqual(display_date("2024:03:05 10:11:12"), "2024-03-05 10:11:12")
        self.assertEqual(display_date("bad"), "")
        self.assertEqual(display_date(None), "")


class GroupingTests(unittest.TestCase):
    def test_pairs_jpg_and_raw(self):
        paths = [
            os.path.join("/photos", "A.ORF"),
            os.path.join("/photos", "A.JPG"),
        ]
        groups = make_groups(paths)
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertTrue(group.is_pair)
        self.assertFalse(group.kind in ("JPG", "ORF"))
        self.assertEqual(
            [os.path.basename(member) for member in group.members], ["A.JPG", "A.ORF"]
        )
        self.assertEqual(os.path.basename(group.primary), "A.JPG")
        self.assertEqual(group.stem, "A")
        self.assertIn("A", group.label)

    def test_same_stem_in_different_directories_stays_separate(self):
        paths = [
            os.path.join("/photos", "A.JPG"),
            os.path.join("/photos", "sub", "A.JPG"),
        ]
        groups = make_groups(paths)
        self.assertEqual(len(groups), 2)

    def test_grouping_disabled(self):
        paths = [
            os.path.join("/photos", "A.JPG"),
            os.path.join("/photos", "A.ORF"),
        ]
        groups = make_groups(paths, group_raw=False)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(not group.is_pair for group in groups))
        self.assertEqual({group.kind for group in groups}, {"JPG", "ORF"})

    def test_filters_and_deduplicates(self):
        paths = [
            os.path.join("/photos", "A.JPG"),
            os.path.join("/photos", ".", "A.JPG"),
            os.path.join("/photos", "notes.txt"),
        ]
        groups = make_groups(paths)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].members), 1)

    def test_normalize_path_is_absolute(self):
        self.assertTrue(os.path.isabs(normalize_path("photo.jpg")))
        self.assertEqual(normalize_path("/photos/A.JPG"), "/photos/A.JPG")


class GroupDateTests(unittest.TestCase):
    def test_priority_within_primary(self):
        group = make_groups(["/photos/A.JPG"])[0]
        metadata = {
            group.key: {},
            normalize_path("/photos/A.JPG"): {
                "DateTimeOriginal": "2021:01:01 00:00:00",
                "CreateDate": "2022:01:01 00:00:00",
            },
        }
        self.assertEqual(
            group_date(group, metadata), "2021:01:01 00:00:00"
        )

    def test_falls_back_to_member(self):
        group = make_groups(["/photos/A.JPG", "/photos/A.ORF"])[0]
        metadata = {
            normalize_path("/photos/A.ORF"): {
                "DateTimeOriginal": "2023:06:07 08:09:10"
            }
        }
        self.assertEqual(group_date(group, metadata), "2023:06:07 08:09:10")

    def test_missing_metadata(self):
        group = make_groups(["/photos/A.JPG"])[0]
        self.assertIsNone(group_date(group, {}))


class SortingTests(unittest.TestCase):
    def _groups(self):
        return make_groups(
            ["/photos/IMG10.JPG", "/photos/IMG2.JPG", "/photos/IMG1.JPG"],
            group_raw=False,
        )

    def test_sort_by_name_natural(self):
        groups = sort_groups(self._groups(), "name")
        self.assertEqual(
            [group.name for group in groups], ["IMG1.JPG", "IMG2.JPG", "IMG10.JPG"]
        )

    def test_sort_by_name_reverse(self):
        groups = sort_groups(self._groups(), "name", reverse=True)
        self.assertEqual(
            [group.name for group in groups], ["IMG10.JPG", "IMG2.JPG", "IMG1.JPG"]
        )

    def test_sort_by_date_with_undated_last(self):
        groups = make_groups(
            ["/photos/a.JPG", "/photos/b.JPG", "/photos/c.JPG"], group_raw=False
        )
        metadata = {
            normalize_path("/photos/a.JPG"): {"DateTimeOriginal": "2021:01:01 00:00:00"},
            normalize_path("/photos/b.JPG"): {"DateTimeOriginal": "2020:01:01 00:00:00"},
        }
        ordered = sort_groups(groups, "date", metadata=metadata)
        self.assertEqual(
            [group.name for group in ordered], ["b.JPG", "a.JPG", "c.JPG"]
        )

    def test_sort_by_date_reverse_keeps_undated_last(self):
        groups = make_groups(
            ["/photos/a.JPG", "/photos/b.JPG", "/photos/c.JPG"], group_raw=False
        )
        metadata = {
            normalize_path("/photos/a.JPG"): {"DateTimeOriginal": "2021:01:01 00:00:00"},
            normalize_path("/photos/b.JPG"): {"DateTimeOriginal": "2020:01:01 00:00:00"},
        }
        ordered = sort_groups(groups, "date", reverse=True, metadata=metadata)
        self.assertEqual(
            [group.name for group in ordered], ["a.JPG", "b.JPG", "c.JPG"]
        )


if __name__ == "__main__":
    unittest.main()
