from __future__ import annotations

import hashlib
import os
import queue
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from PIL import Image

from config import cache_dir
from file_model import normalize_path
from image_utils import load_preview_image

POLL_INTERVAL_MS = 50
WORKER_COUNT = 3


class ThumbnailCache:
    def __init__(self, root, size: int = 160, max_memory: int = 300):
        self.root = root
        self.size = int(size)
        self.max_memory = max_memory
        self.directory = cache_dir() / "thumbnails"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._memory: OrderedDict[str, Image.Image] = OrderedDict()
        self._callbacks: dict[str, list[Callable]] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._queue: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._generation = 0
        self._workers = [
            threading.Thread(target=self._worker, daemon=True) for _ in range(WORKER_COUNT)
        ]
        for worker in self._workers:
            worker.start()
        self._poll_id = self.root.after(POLL_INTERVAL_MS, self._poll)

    def get(self, file_path, callback: Callable) -> None:
        key = normalize_path(file_path)
        cached = self._memory.get(key)
        if cached is not None:
            self._memory.move_to_end(key)
            callback(cached)
            return
        if key in self._failed:
            callback(None)
            return
        self._callbacks.setdefault(key, []).append(callback)
        if key in self._pending:
            return
        try:
            mtime = os.stat(key).st_mtime_ns
        except OSError:
            self._failed.add(key)
            for pending in self._callbacks.pop(key, []):
                pending(None)
            return
        self._pending.add(key)
        self._queue.put((key, mtime, self.size, self._generation))

    def set_size(self, size: int) -> None:
        size = int(size)
        if size == self.size:
            return
        self.size = size
        self._generation += 1
        self._memory.clear()
        self._pending.clear()
        self._callbacks.clear()

    def shutdown(self) -> None:
        self._stop.set()
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _cache_path(self, key: str, mtime: int, size: int) -> Path:
        digest = hashlib.sha1(f"{key}|{mtime}|{size}".encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.jpg"

    def _load_cached(self, key: str, mtime: int, size: int) -> Image.Image | None:
        path = self._cache_path(key, mtime, size)
        try:
            with Image.open(path) as image:
                image.load()
                return image.copy()
        except Exception:
            return None

    def _store_cached(self, key: str, mtime: int, size: int, image: Image.Image) -> None:
        path = self._cache_path(key, mtime, size)
        try:
            image.save(path, "JPEG", quality=85)
        except OSError:
            pass

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                key, mtime, size, generation = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                thumbnail = self._load_cached(key, mtime, size)
                if thumbnail is None:
                    image = load_preview_image(key)
                    if image is None:
                        raise ValueError("no preview")
                    image.thumbnail((size, size), Image.Resampling.LANCZOS)
                    thumbnail = image.convert("RGB")
                    self._store_cached(key, mtime, size, thumbnail)
                self._results.put((key, thumbnail, generation))
            except Exception:
                self._results.put((key, None, generation))
            finally:
                self._queue.task_done()

    def _poll(self) -> None:
        try:
            while True:
                key, image, generation = self._results.get_nowait()
                if generation != self._generation:
                    continue
                self._pending.discard(key)
                if image is None:
                    self._failed.add(key)
                else:
                    self._memory[key] = image
                    self._memory.move_to_end(key)
                    while len(self._memory) > self.max_memory:
                        self._memory.popitem(last=False)
                callbacks = self._callbacks.pop(key, [])
                for callback in callbacks:
                    try:
                        callback(image)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self._poll_id = self.root.after(POLL_INTERVAL_MS, self._poll)
