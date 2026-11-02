from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".orf"}
RAW_EXTENSIONS = {".orf"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}

DATE_TAG_PRIORITY = ("DateTimeOriginal", "CreateDate", "ModifyDate", "FileModifyDate")


def normalize_path(path: str | os.PathLike) -> str:
    return os.path.abspath(os.path.expanduser(os.fspath(path)))


def natural_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", value.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    match = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", text)
    if not match:
        return None
    try:
        return datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def display_date(value: str | None) -> str:
    parsed = parse_exif_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class FileGroup:
    key: str
    primary: str
    members: tuple[str, ...]
    kind: str

    @property
    def name(self) -> str:
        return os.path.basename(self.primary)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]

    @property
    def directory(self) -> str:
        return os.path.dirname(self.primary)

    @property
    def is_pair(self) -> bool:
        return len(self.members) > 1

    @property
    def label(self) -> str:
        if self.is_pair:
            return f"{self.stem}  ({self.kind})"
        return self.name


def _group_key(path: str, group_raw: bool) -> str:
    if not group_raw:
        return path
    directory = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{directory}\x00{stem}"


def _kind_for_extensions(extensions: set[str]) -> str:
    has_jpeg = bool(extensions & JPEG_EXTENSIONS)
    has_raw = bool(extensions & RAW_EXTENSIONS)
    if has_jpeg and has_raw:
        return "JPG+ORF"
    if has_jpeg:
        return "JPG"
    return "ORF"


def _member_order(path: str) -> tuple[int, str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in JPEG_EXTENSIONS:
        return (0, path.lower())
    if ext in RAW_EXTENSIONS:
        return (1, path.lower())
    return (2, path.lower())


def make_groups(paths: list[str] | tuple[str, ...], group_raw: bool = True) -> list[FileGroup]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = normalize_path(raw_path)
        if path in seen:
            continue
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        seen.add(path)
        ordered.append(path)

    buckets: dict[str, list[str]] = {}
    for path in ordered:
        buckets.setdefault(_group_key(path, group_raw), []).append(path)

    groups: list[FileGroup] = []
    for key, members in buckets.items():
        members.sort(key=_member_order)
        extensions = {os.path.splitext(member)[1].lower() for member in members}
        primary = members[0]
        groups.append(
            FileGroup(
                key=key,
                primary=primary,
                members=tuple(members),
                kind=_kind_for_extensions(extensions),
            )
        )
    return groups


def group_date(group: FileGroup, metadata: dict[str, dict[str, str]]) -> str | None:
    candidates = (group.primary, *group.members)
    for path in candidates:
        meta = metadata.get(normalize_path(path), {})
        for tag in DATE_TAG_PRIORITY:
            value = meta.get(tag)
            if value:
                return value
    return None


def sort_groups(
    groups: list[FileGroup],
    field: str = "name",
    reverse: bool = False,
    metadata: dict[str, dict[str, str]] | None = None,
) -> list[FileGroup]:
    items = list(groups)
    if field == "date" and metadata is not None:
        dated: list[tuple[datetime, tuple, FileGroup]] = []
        undated: list[FileGroup] = []
        for group in items:
            parsed = parse_exif_datetime(group_date(group, metadata))
            if parsed is None:
                undated.append(group)
            else:
                dated.append((parsed, natural_key(group.name), group))
        dated.sort(key=lambda item: (item[0], item[1]), reverse=reverse)
        undated.sort(key=lambda group: natural_key(group.name), reverse=reverse)
        return [item[2] for item in dated] + undated
    if field == "date":
        return sorted(items, key=lambda group: natural_key(group.name), reverse=reverse)
    return sorted(items, key=lambda group: natural_key(group.name), reverse=reverse)
