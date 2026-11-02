#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from file_model import normalize_path, parse_exif_datetime

DATE_TAGS = ("DateTimeOriginal", "CreateDate", "ModifyDate", "FileModifyDate")
METADATA_TAGS = ("OwnerName", "Artist", "Copyright", "ImageDescription")
ALL_TAGS = (*DATE_TAGS, *METADATA_TAGS)


def find_exiftool():
    script_dir = Path(__file__).parent
    candidates = [
        script_dir / "exiftool-bin" / "exiftool",
        script_dir / "exiftool",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and os.access(path, os.X_OK):
            return str(path.resolve())
    return "exiftool"


EXIFTOOL = find_exiftool()


def _unique_paths(file_paths) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in file_paths:
        normalized = normalize_path(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def read_metadata(file_paths) -> dict[str, dict[str, str]]:
    paths = _unique_paths(file_paths)
    if not paths:
        return {}
    cmd = [EXIFTOOL, "-j", *[f"-{tag}" for tag in ALL_TAGS], *paths]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    if not proc.stdout:
        return {}
    try:
        records = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return {}
    if not isinstance(records, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source = record.get("SourceFile")
        if not source:
            continue
        key = normalize_path(source)
        values: dict[str, str] = {}
        for tag in ALL_TAGS:
            value = record.get(tag)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                values[tag] = text
        result[key] = values
    return result


def read_alldates(file_paths) -> dict[str, str]:
    result: dict[str, str] = {}
    for path, metadata in read_metadata(file_paths).items():
        for tag in DATE_TAGS:
            value = metadata.get(tag)
            if value:
                result[path] = value
                break
    return result


def _run_write(arguments: list[str], file_paths) -> tuple[bool, str]:
    paths = _unique_paths(file_paths)
    if not paths:
        return False, "No files"
    cmd = [EXIFTOOL, "-overwrite_original", *arguments, *paths]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    message = out or err
    if proc.returncode != 0:
        return False, message or "exiftool failed"
    return True, message or f"Updated {len(paths)} file(s)"


def set_alldates(file_paths, date_str: str) -> tuple[bool, str]:
    if not date_str:
        return False, "No date"
    if not re.match(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$", date_str):
        return False, "Invalid date format. Use YYYY:MM:DD HH:MM:SS"
    return _run_write([f"-AllDates={date_str}"], file_paths)


def parse_offset(offset_str: str) -> timedelta:
    text = offset_str.strip().lower()
    if not text:
        raise ValueError("Empty offset")
    matches = list(re.finditer(r"([+-]?)(\d+)([dhms])", text))
    if not matches:
        raise ValueError("Invalid offset. Use e.g. -1d, +10h, -30m, +2d3h")
    remainder = re.sub(r"[+-]?\d+[dhms]", "", text).strip()
    if remainder:
        raise ValueError(f"Invalid offset near '{remainder}'")
    total_seconds = 0
    sign = 1
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    for match in matches:
        prefix, number, unit = match.groups()
        if prefix == "-":
            sign = -1
        elif prefix == "+":
            sign = 1
        total_seconds += sign * int(number) * multipliers[unit]
    return timedelta(seconds=total_seconds)


def _first_date(metadata: dict[str, str] | None) -> str | None:
    if not metadata:
        return None
    for tag in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
        value = metadata.get(tag)
        if value:
            return value
    return None


def apply_offset(file_paths, offset_str: str, metadata: dict[str, dict[str, str]] | None = None):
    paths = _unique_paths(file_paths)
    if not paths:
        return False, "No files"
    try:
        delta = parse_offset(offset_str)
    except ValueError as error:
        return False, str(error)
    if metadata is None:
        metadata = read_metadata(paths)
    success = 0
    errors: list[str] = []
    for path in paths:
        current = _first_date(metadata.get(path))
        if not current:
            errors.append(f"{os.path.basename(path)}: no date found")
            continue
        parsed = parse_exif_datetime(current)
        if parsed is None:
            errors.append(f"{os.path.basename(path)}: invalid date '{current}'")
            continue
        new_value = (parsed + delta).strftime("%Y:%m:%d %H:%M:%S")
        ok, message = set_alldates([path], new_value)
        if ok:
            success += 1
        else:
            errors.append(f"{os.path.basename(path)}: {message}")
    summary = f"Updated {success}/{len(paths)} files."
    if errors:
        summary += " " + "; ".join(errors)
    return success > 0, summary


def set_date_keep_time(
    file_paths,
    new_date_str: str,
    metadata: dict[str, dict[str, str]] | None = None,
):
    paths = _unique_paths(file_paths)
    if not paths:
        return False, "No files"
    if not new_date_str:
        return False, "No date"
    normalized = new_date_str.strip().replace("-", ":")
    try:
        new_date = datetime.strptime(normalized, "%Y:%m:%d")
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD"
    if metadata is None:
        metadata = read_metadata(paths)
    success = 0
    errors: list[str] = []
    for path in paths:
        current = _first_date(metadata.get(path))
        if not current:
            errors.append(f"{os.path.basename(path)}: no date found")
            continue
        parsed = parse_exif_datetime(current)
        if parsed is None:
            errors.append(f"{os.path.basename(path)}: invalid date '{current}'")
            continue
        new_value = new_date.replace(hour=parsed.hour, minute=parsed.minute, second=parsed.second)
        ok, message = set_alldates([path], new_value.strftime("%Y:%m:%d %H:%M:%S"))
        if ok:
            success += 1
        else:
            errors.append(f"{os.path.basename(path)}: {message}")
    summary = f"Updated {success}/{len(paths)} files."
    if errors:
        summary += " " + "; ".join(errors)
    return success > 0, summary


def set_metadata(file_paths, fields: dict[str, str | None]) -> tuple[bool, str]:
    paths = _unique_paths(file_paths)
    if not paths:
        return False, "No files"
    if not fields:
        return False, "No metadata fields"
    arguments: list[str] = []
    for tag, value in fields.items():
        if tag not in METADATA_TAGS:
            return False, f"Unsupported metadata field: {tag}"
        if value is None:
            arguments.append(f"-{tag}=")
        else:
            arguments.append(f"-{tag}={value}")
    return _run_write(arguments, paths)
