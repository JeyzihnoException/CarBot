import json
from pathlib import Path
from typing import Any


class JsonStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self, default: Any) -> Any:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return default

        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def write(self, data: Any) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
