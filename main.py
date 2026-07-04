import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import settings
from models.car import CachedCarRecord, RankedCar
from providers.registry import get_provider
from service.ai_service import LlmRanker
from storage.car_cache import CarCacheStorage


logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

CACHE_TOP_N = 3
MODE_AWAITING_LINK = "awaiting_link"


def extract_url(text: str) -> str | None:
    for part in text.split():
        if part.startswith("http://") or part.startswith("https://"):
            return part.strip()
    return None


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Показать топ", callback_data="show_top")],
            [InlineKeyboardButton(text="Анализ объявлений", callback_data="analyze")],
        ]
    )


def models_menu(models: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for index, model in enumerate(models):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{model['model_label']} ({model['count']})",
                    callback_data=f"model_top:{index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_result(item: RankedCar, index: int) -> str:
    car = item.car
    price = car.price or "нет данных"
    equipment = item.equipment or "нет данных"
    pros = "; ".join(item.pros) if item.pros else "нет явных плюсов"
    cons = "; ".join(item.cons) if item.cons else "нет явных рисков по данным объявления"
    verdict = item.recommendation or item.summary or "недостаточно данных для уверенного вывода"

    parts = [
        f"Вариант {index}: {item.title}",
        f"Рейтинг: {item.score}/100",
        car.url,
        f"1. Цена: {price}",
        f"2. Комплектация: {equipment}",
        f"3. Плюсы: {pros}",
        f"4. Риски: {cons}",
    ]

    if item.questions:
        parts.append("5. Что спросить: " + "; ".join(item.questions))

    parts.append(f"6. Вердикт: {verdict}")
    return "\n".join(parts)


def format_top(model_label: str, total: int, ranked: list[RankedCar]) -> str:
    header = f"Модель: {model_label}\nВсего в кэше: {total}\nТоп {len(ranked)}:"
    chunks = [header] + [format_result(item, index) for index, item in enumerate(ranked, start=1)]
    return "\n\n".join(chunks)


async def analyze_url(url: str, top_n: int) -> tuple[str, str, int, list[RankedCar]]:
    provider = get_provider(url)
    if not provider:
        raise ValueError("Пока поддерживается только Auto.ru.")

    ranker = LlmRanker()
    cache = CarCacheStorage()

    links = await provider.get_listing_links(url, limit=settings.max_ads_to_scan)
    if not links:
        raise ValueError("Не нашел ссылки на объявления в этой выдаче.")

    cars = await provider.get_car_details(links)
    cars = [car for car in cars if car.title or car.raw_text]
    if not cars:
        raise ValueError("Не удалось собрать данные объявлений.")

    model_key, model_label = provider.get_model_identity(url, cars)
    seen_urls = cache.seen_urls(model_key)
    fresh_cars = [car for car in cars if car.url not in seen_urls]

    if fresh_cars:
        evaluated = await ranker.rank(cars=fresh_cars)
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

    return model_key, model_label, cache.count(model_key), cache.top_ranked(model_key, top_n)


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in environment")

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    top_by_user: dict[int, int] = {}
    mode_by_user: dict[int, str] = {}
    model_options_by_user: dict[int, list[dict]] = {}

    @dp.message(Command("start"))
    async def start(message: Message) -> None:
        mode_by_user.pop(message.from_user.id, None)
        await message.answer("Выбери действие:", reply_markup=main_menu())

    @dp.message(Command("top"))
    async def set_top(message: Message, command: CommandObject) -> None:
        try:
            value = int((command.args or "").strip())
        except ValueError:
            await message.answer("Использование: /top 5")
            return

        if value < 1 or value > settings.max_top_n:
            await message.answer(f"Укажи число от 1 до {settings.max_top_n}.")
            return

        top_by_user[message.from_user.id] = value
        await message.answer(f"Размер топа после анализа: {value}")

    @dp.callback_query(F.data == "main_menu")
    async def show_main_menu(callback: CallbackQuery) -> None:
        mode_by_user.pop(callback.from_user.id, None)
        await callback.message.edit_text("Выбери действие:", reply_markup=main_menu())
        await callback.answer()

    @dp.callback_query(F.data == "analyze")
    async def ask_link(callback: CallbackQuery) -> None:
        mode_by_user[callback.from_user.id] = MODE_AWAITING_LINK
        await callback.message.edit_text(
            "Пришли ссылку Auto.ru с выбранными фильтрами.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="main_menu")]]
            ),
        )
        await callback.answer()

    @dp.callback_query(F.data == "show_top")
    async def show_models(callback: CallbackQuery) -> None:
        cache = CarCacheStorage()
        models = cache.list_models()

        if not models:
            await callback.message.edit_text(
                "В кэше пока нет моделей. Сначала запусти анализ объявлений.",
                reply_markup=main_menu(),
            )
            await callback.answer()
            return

        model_options_by_user[callback.from_user.id] = models
        await callback.message.edit_text("Выбери модель:", reply_markup=models_menu(models))
        await callback.answer()

    @dp.callback_query(F.data.startswith("model_top:"))
    async def show_model_top(callback: CallbackQuery) -> None:
        try:
            index = int((callback.data or "").split(":", 1)[1])
            model = model_options_by_user.get(callback.from_user.id, [])[index]
        except (ValueError, IndexError):
            await callback.answer("Список моделей устарел. Открой его заново.", show_alert=True)
            return

        cache = CarCacheStorage()
        ranked = cache.top_ranked(model["model_key"], CACHE_TOP_N)
        if not ranked:
            await callback.answer("По этой модели пока нет оцененных объявлений.", show_alert=True)
            return

        text = format_top(model["model_label"], cache.count(model["model_key"]), ranked)
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="К моделям", callback_data="show_top")]]
            ),
            disable_web_page_preview=True,
        )
        await callback.answer()

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        user_id = message.from_user.id
        url = extract_url(message.text or "")

        if not url:
            await message.answer("Выбери действие:", reply_markup=main_menu())
            return

        if mode_by_user.get(user_id) != MODE_AWAITING_LINK:
            mode_by_user[user_id] = MODE_AWAITING_LINK

        top_n = top_by_user.get(user_id, settings.default_top_n)
        await message.answer("Начинаю анализ. Это может занять несколько минут.")

        try:
            _, model_label, total, ranked = await analyze_url(url, top_n)
        except ValueError as error:
            await message.answer(str(error), reply_markup=main_menu())
            return
        except Exception:
            logger.exception("Failed to process search url")
            await message.answer("Ошибка при обработке ссылки. Подробности смотри в логах.", reply_markup=main_menu())
            return
        finally:
            mode_by_user.pop(user_id, None)

        if not ranked:
            await message.answer("Пока нет данных в кэше для этой модели.", reply_markup=main_menu())
            return

        await message.answer(format_top(model_label, total, ranked), reply_markup=main_menu(), disable_web_page_preview=True)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
