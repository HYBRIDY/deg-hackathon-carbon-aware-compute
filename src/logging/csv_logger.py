"""CSV event logger with reusable schema and thread safety."""

from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, Iterable


class CsvEventLogger:
    """Append-only CSV logger with header management and thread safety."""

    _lock = threading.Lock()

    def __init__(self, path: str, fieldnames: Iterable[str]):
        self.path = path
        self.fieldnames = list(fieldnames)
        self._ensure_header()

    def _ensure_header(self) -> None:
        is_new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        if is_new:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", newline="", encoding="utf-8") as file_obj:
                csv.DictWriter(file_obj, fieldnames=self.fieldnames).writeheader()

    def append(self, row: Dict) -> None:
        flat = {key: row.get(key, "") for key in self.fieldnames}
        runtime_parameters = flat.get("runtime_parameters")
        if isinstance(runtime_parameters, dict):
            flat["runtime_parameters"] = json.dumps(runtime_parameters, ensure_ascii=False)

        with self._lock:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", newline="", encoding="utf-8") as file_obj:
                csv.DictWriter(file_obj, fieldnames=self.fieldnames).writerow(flat)


def now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with millisecond precision."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = ["CsvEventLogger", "now_iso"]

