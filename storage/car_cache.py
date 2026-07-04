from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from config import settings
from models.car import CachedCarRecord, RankedCar
from storage.storage import JsonStorage


class CarCacheStorage:
    def __init__(self, path: str | Path | None = None) -> None:
        self.storage = JsonStorage(path or settings.car_cache_path)

    def load(self) -> dict:
        data = self.storage.read({"models": {}})
        if not isinstance(data, dict):
            return {"models": {}}
        data.setdefault("models", {})
        return data

    def save(self, data: dict) -> None:
        self.storage.write(data)

    def seen_urls(self, model_key: str) -> set[str]:
        model = self._get_model(model_key)
        return {
            str(record.get("car", {}).get("url", ""))
            for record in model.get("records", [])
            if record.get("car", {}).get("url")
        }

    def upsert_many(self, records: Iterable[CachedCarRecord]) -> int:
        data = self.load()
        models = data.setdefault("models", {})
        updated = 0

        for record in records:
            model = models.setdefault(
                record.model_key,
                {"model_key": record.model_key, "model_label": record.model_label, "records": []},
            )
            model["model_label"] = record.model_label or model.get("model_label", "")
            model_records = model.setdefault("records", [])
            url = record.car.url
            model_records = [existing for existing in model_records if existing.get("car", {}).get("url") != url]
            model_records.append(record.to_dict())
            model["records"] = model_records
            updated += 1

        self.save(data)
        return updated

    def top_ranked(self, model_key: str, limit: int) -> list[RankedCar]:
        model = self._get_model(model_key)
        records = [CachedCarRecord.from_dict(item) for item in model.get("records", [])]
        records.sort(key=lambda item: (item.score, item.evaluated_at), reverse=True)
        ranked: list[RankedCar] = []

        for record in records[:limit]:
            ranked.append(
                RankedCar(
                    car=record.car,
                    score=record.score,
                    title=record.title or record.car.title or record.car.url,
                    summary=record.summary,
                    equipment=record.equipment,
                    pros=record.pros,
                    cons=record.cons,
                    questions=record.questions,
                    recommendation=record.recommendation,
                )
            )

        return ranked

    def count(self, model_key: str) -> int:
        return len(self._get_model(model_key).get("records", []))

    def list_models(self) -> list[dict]:
        data = self.load()
        models = []

        for model_key, model in data.get("models", {}).items():
            count = len(model.get("records", []))
            if count == 0:
                continue
            models.append(
                {
                    "model_key": model_key,
                    "model_label": model.get("model_label") or model_key,
                    "count": count,
                }
            )

        return sorted(models, key=lambda item: item["model_label"].lower())

    def _get_model(self, model_key: str) -> dict:
        data = self.load()
        return data.get("models", {}).get(model_key, {"records": []})
