import argparse
import asyncio
import logging

from config import settings
from models.car import CachedCarRecord
from providers.registry import get_provider
from storage.car_cache import CarCacheStorage
from service.ai_service import LlmRanker


logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def print_car(car, index: int) -> None:
    print(f"\n{index}. {car.title or 'Без названия'}")
    print(f"URL: {car.url}")
    if car.price:
        print(f"Цена: {car.price}")
    if car.year:
        print(f"Год: {car.year}")
    if car.mileage:
        print(f"Пробег: {car.mileage}")
    if car.location:
        print(f"Город: {car.location}")
    if car.specs:
        print("Характеристики:")
        for key, value in list(car.specs.items())[:12]:
            print(f"  {key}: {value}")


async def run(search_url: str, limit: int, top: int, no_llm: bool) -> None:
    provider = get_provider(search_url)
    if not provider:
        raise RuntimeError("Only Auto.ru is supported for now")

    cache = CarCacheStorage()

    print("Собираю ссылки с выдачи...")
    links = await provider.get_listing_links(search_url, limit=limit)
    print(f"Найдено ссылок: {len(links)}")

    if not links:
        return

    print("Собираю карточки объявлений...")
    cars = await provider.get_car_details(links)
    cars = [car for car in cars if car.title or car.raw_text]
    print(f"Собрано карточек: {len(cars)}")

    if no_llm:
        for index, car in enumerate(cars, start=1):
            print_car(car, index)
        return

    model_key, model_label = provider.get_model_identity(search_url, cars)
    seen_urls = cache.seen_urls(model_key)
    fresh_cars = [car for car in cars if car.url not in seen_urls]

    if fresh_cars:
        print(f"Новых объявлений для оценки: {len(fresh_cars)}")
        print("Отправляю новые данные в LLM...")
        evaluated = await LlmRanker().rank(cars=fresh_cars)
        cache.upsert_many(
            CachedCarRecord(
                model_key=model_key,
                model_label=model_label,
                car=item.car,
                score=item.score,
                title=item.title,
                summary=item.summary,
                equipment=item.equipment,
                pros=item.pros,
                cons=item.cons,
                questions=item.questions,
                recommendation=item.recommendation,
            )
            for item in evaluated
        )
    else:
        print("Новых объявлений нет, использую кэш.")

    ranked = cache.top_ranked(model_key, top)
    total = cache.count(model_key)

    print(f"\nМодель: {model_label}")
    print(f"Всего в кэше: {total}")
    print(f"TOP {len(ranked)}")
    for index, item in enumerate(ranked, start=1):
        print(f"\nВариант {index}: {item.title}")
        print(item.car.url)
        print(f"1. Цена: {item.car.price or 'нет данных'}")
        print(f"2. Комплектация: {item.equipment or 'нет данных'}")
        print("3. Плюсы: " + ("; ".join(item.pros) if item.pros else "нет явных плюсов"))
        print(
            "4. Риски: "
            + ("; ".join(item.cons) if item.cons else "нет явных рисков по данным объявления")
        )
        if item.questions:
            print("5. Что спросить: " + "; ".join(item.questions))
        print(
            "6. Вердикт: "
            + (item.recommendation or item.summary or "недостаточно данных для уверенного вывода")
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Auto.ru parser without Telegram")
    parser.add_argument("url", help="Auto.ru search URL with selected filters")
    parser.add_argument("--limit", type=int, default=5, help="How many ads to scan")
    parser.add_argument("--top", type=int, default=settings.default_top_n, help="How many cars to return")
    parser.add_argument("--no-llm", action="store_true", help="Only parse listings, skip LLM ranking")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.url, args.limit, args.top, args.no_llm))
