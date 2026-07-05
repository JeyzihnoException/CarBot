import asyncio
import json
import logging
import re
from typing import Any

import httpx
from google import genai
from google.genai import types
from openai import AsyncOpenAI

from config import settings
from models.car import CarDetails, RankedCar


logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_PROMPT = """
Ты опытный эксперт по подбору автомобилей с большим опытом осмотра подержанных машин.

Тебе будут переданы данные, собранные из объявлений о продаже автомобиля.

Доступные данные:
- url — ссылка на объявление
- source — сайт, на котором размещено объявление
- title — заголовок объявления
- price — цена
- year — год выпуска
- mileage — пробег
- location — город
- seller — информация о продавце
- specs — характеристики автомобиля
- description — описание от продавца
- raw_text — текст страницы, который может содержать дополнительную информацию, не попавшую в отдельные поля

Используй все доступные данные. Если какая-то информация отсутствует, не делай предположений.

Твоя задача:
- кратко оценить каждое объявление;
- отметить сильные стороны автомобиля;
- указать возможные риски и подозрительные моменты;
- обратить внимание на несоответствия, если они есть;
- предложить, какие вопросы стоит задать продавцу;
- дать рекомендацию, стоит ли рассматривать автомобиль дальше.

Не пересказывай объявление. Делай выводы.
Если данных недостаточно для уверенной оценки, прямо скажи об этом.
Ответ должен быть коротким, информативным.
Верни только JSON без markdown.
""".strip()


class LlmRanker:
    async def rank(self, cars: list[CarDetails]) -> list[RankedCar]:
        provider = settings.llm_provider.strip().lower()

        if provider == "gemini":
            data = await self._rank_with_gemini(cars=cars)
        elif provider == "openai":
            data = await self._rank_with_openai(cars=cars)
        else:
            raise RuntimeError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

        return self._parse_ranked_items(data=data, cars=cars)

    async def _rank_with_gemini(self, cars: list[CarDetails]) -> dict[str, Any]:
        if not settings.gemini_api_key:
            raise RuntimeError("Set GEMINI_API_KEY in environment")

        prompt = self._user_prompt(cars=cars)

        def call_gemini() -> str:
            client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=self._gemini_http_options(),
            )
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config={
                    "system_instruction": self._system_prompt(),
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
            )
            return response.text or "{}"

        content = await asyncio.to_thread(call_gemini)
        return json.loads(self._extract_json(content))

    async def _rank_with_openai(self, cars: list[CarDetails]) -> dict[str, Any]:
        if not settings.openai_api_key:
            raise RuntimeError("Set OPENAI_API_KEY in environment")

        http_client = self._openai_http_client()
        client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=http_client)
        try:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._user_prompt(cars=cars)},
                ],
            )
        finally:
            if http_client is not None:
                await http_client.aclose()

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _proxy_url(self) -> str:
        return settings.llm_proxy_url.strip()

    def _gemini_http_options(self) -> types.HttpOptions | None:
        proxy_url = self._proxy_url()
        if not proxy_url:
            return None

        return types.HttpOptions(
            clientArgs={
                "proxy": proxy_url,
                "trust_env": False,
            },
        )

    def _openai_http_client(self) -> httpx.AsyncClient | None:
        proxy_url = self._proxy_url()
        if not proxy_url:
            return None

        return httpx.AsyncClient(
            proxy=proxy_url,
            trust_env=False,
        )

    def _user_prompt(self, cars: list[CarDetails]) -> str:
        payload = {
            "count": len(cars),
            "cars": [self._car_payload(index, car) for index, car in enumerate(cars)],
        }

        return (
            "Оцени каждое объявление отдельно, не сравнивая его с другими из списка. "
            "Верни JSON строго вида "
            '{"items":[{"index":0,"score":85,"title":"...",'
            '"summary":"...","equipment":"...","pros":["..."],"cons":["..."],'
            '"questions":["..."],"recommendation":"..."}]}. '
            "index должен соответствовать индексу машины из входных данных. "
            "score: целое число от 0 до 100, это независимая оценка конкретной машины по всем параметрам. "
            "summary: короткая экспертная оценка, не пересказ. "
            "equipment: самая важная информация о комплектации и характеристиках в одну короткую строку. "
            "pros: сильные стороны. "
            "cons: риски, подозрительные моменты и несоответствия. "
            "questions: вопросы продавцу перед осмотром. "
            "recommendation: короткий вывод, стоит ли рассматривать дальше. "
            "Все текстовые поля пиши по-русски.\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    def _system_prompt(self) -> str:
        return settings.llm_system_prompt.strip() or DEFAULT_SYSTEM_PROMPT

    def _car_payload(self, index: int, car: CarDetails) -> dict[str, Any]:
        return {
            "index": index,
            "url": car.url,
            "source": car.source,
            "title": car.title,
            "price": car.price,
            "year": car.year,
            "mileage": car.mileage,
            "location": car.location,
            "seller": car.seller,
            "specs": car.specs,
            "description": car.description,
            "raw_text": car.raw_text[:4_000],
        }

    def _parse_ranked_items(
        self,
        data: dict[str, Any],
        cars: list[CarDetails],
    ) -> list[RankedCar]:
        items = data.get("items", [])
        ranked: list[RankedCar] = []

        for item in items:
            try:
                car = cars[int(item["index"])]
            except (KeyError, ValueError, IndexError, TypeError):
                logger.warning("LLM returned invalid item index: %s", item)
                continue

            ranked.append(
                RankedCar(
                    car=car,
                    score=int(item.get("score", 0)),
                    title=str(item.get("title") or car.title or car.url),
                    summary=str(item.get("summary", "")),
                    equipment=str(item.get("equipment", "")),
                    pros=[str(value) for value in item.get("pros", [])],
                    cons=[str(value) for value in item.get("cons", [])],
                    questions=[str(value) for value in item.get("questions", [])],
                    recommendation=str(item.get("recommendation", "")),
                )
            )

        return ranked

    def _extract_json(self, content: str) -> str:
        content = content.strip()
        if content.startswith("{"):
            return content

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced:
            return fenced.group(1)

        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return content[start : end + 1]

        raise ValueError("LLM response does not contain JSON")
