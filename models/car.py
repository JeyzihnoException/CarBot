from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class CarDetails:
    url: str
    source: str
    title: str = ""
    price: str = ""
    year: int | None = None
    mileage: str = ""
    location: str = ""
    seller: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    description: str = ""
    raw_text: str = ""


@dataclass(frozen=True)
class RankedCar:
    car: CarDetails
    score: int
    title: str
    summary: str
    equipment: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass(frozen=True)
class CachedCarRecord:
    model_key: str
    model_label: str
    car: CarDetails
    score: int
    title: str
    summary: str
    equipment: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    recommendation: str = ""
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "model_key": self.model_key,
            "model_label": self.model_label,
            "car": {
                "url": self.car.url,
                "source": self.car.source,
                "title": self.car.title,
                "price": self.car.price,
                "year": self.car.year,
                "mileage": self.car.mileage,
                "location": self.car.location,
                "seller": self.car.seller,
                "specs": self.car.specs,
                "description": self.car.description,
                "raw_text": self.car.raw_text,
            },
            "score": self.score,
            "title": self.title,
            "summary": self.summary,
            "equipment": self.equipment,
            "pros": self.pros,
            "cons": self.cons,
            "questions": self.questions,
            "recommendation": self.recommendation,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CachedCarRecord":
        car_data = data.get("car", {})
        car = CarDetails(
            url=car_data.get("url", ""),
            source=car_data.get("source", ""),
            title=car_data.get("title", ""),
            price=car_data.get("price", ""),
            year=car_data.get("year"),
            mileage=car_data.get("mileage", ""),
            location=car_data.get("location", ""),
            seller=car_data.get("seller", ""),
            specs=dict(car_data.get("specs", {}) or {}),
            description=car_data.get("description", ""),
            raw_text=car_data.get("raw_text", ""),
        )

        return cls(
            model_key=data.get("model_key", ""),
            model_label=data.get("model_label", ""),
            car=car,
            score=int(data.get("score", 0)),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            equipment=data.get("equipment", ""),
            pros=[str(value) for value in data.get("pros", [])],
            cons=[str(value) for value in data.get("cons", [])],
            questions=[str(value) for value in data.get("questions", [])],
            recommendation=data.get("recommendation", ""),
            evaluated_at=data.get("evaluated_at", ""),
        )
