from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "exif-date-editor"

DEFAULTS = {
    "version": 1,
    "recent_dirs": [],
    "last_picker_dir": "",
    "sort_field": "name",
    "sort_reverse": False,
    "view_mode": "grid",
    "group_raw_jpg": True,
    "thumbnail_size": 160,
    "window_geometry": "1100x760",
}

MAX_RECENT_DIRS = 10


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / APP_NAME


def default_picker_dir(last_picker: str = "") -> str:
    if last_picker:
        candidate = Path(last_picker).expanduser()
        if candidate.is_dir():
            return str(candidate)
    pictures = Path.home() / "Pictures"
    if pictures.is_dir():
        return str(pictures)
    return str(Path.home())


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else config_dir() / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, default in DEFAULTS.items():
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(default, list) and not isinstance(value, list):
                continue
            if isinstance(default, dict) and not isinstance(value, dict):
                continue
            self.data[key] = value

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(self.path.name + ".tmp")
            tmp_path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp_path, self.path)
            return True
        except OSError:
            return False

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def recent_dirs(self) -> list[str]:
        return [str(p) for p in self.data.get("recent_dirs", []) if p]

    def add_recent_dir(self, directory: str | os.PathLike) -> None:
        try:
            normalized = str(Path(directory).expanduser().resolve())
        except OSError:
            normalized = str(directory)
        recents = [p for p in self.recent_dirs() if p != normalized]
        recents.insert(0, normalized)
        self.data["recent_dirs"] = recents[:MAX_RECENT_DIRS]
        self.data["last_picker_dir"] = normalized
        self.save()

    def clear_recent_dirs(self) -> None:
        self.data["recent_dirs"] = []
        self.save()

    def remember_picker_dir(self, directory: str | os.PathLike) -> None:
        try:
            normalized = str(Path(directory).expanduser().resolve())
        except OSError:
            normalized = str(directory)
        self.data["last_picker_dir"] = normalized
        self.save()

    def picker_dir(self) -> str:
        return default_picker_dir(str(self.data.get("last_picker_dir", "")))
