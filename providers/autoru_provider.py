import json
import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, TimeoutError, async_playwright

from config import settings
from models.car import CarDetails
from providers.base import ListingProvider


logger = logging.getLogger(__name__)


class AutoRuProvider(ListingProvider):
    source = "auto.ru"

    async def get_listing_links(self, search_url: str, limit: int | None = None) -> list[str]:
        async with async_playwright() as p:
            context = await self._new_context(p)
            try:
                page = await context.new_page()
                await page.goto(search_url, wait_until="domcontentloaded", timeout=settings.default_timeout_ms)
                await self._accept_region_dialog(page)
                await self._scroll_results(page)

                hrefs = await page.locator("a[href*='/cars/used/sale/']").evaluate_all(
                    "(nodes) => nodes.map((node) => node.href)"
                )
                links = self._unique_links(hrefs)
                return links[:limit] if limit else links
            finally:
                await context.close()

    async def get_car_details(self, links: list[str]) -> list[CarDetails]:
        cars: list[CarDetails] = []
        async with async_playwright() as p:
            context = await self._new_context(p)
            try:
                page = await context.new_page()
                for url in links:
                    try:
                        car = await self._parse_car_page(page, url)
                        cars.append(car)
                    except Exception:
                        logger.exception("Failed to parse Auto.ru ad: %s", url)
            finally:
                await context.close()
        return cars

    def get_model_identity(self, search_url: str, cars: list[CarDetails]) -> tuple[str, str]:
        parsed = urlsplit(search_url)
        params = parse_qs(parsed.query)
        catalog_filters = params.get("catalog_filter", [])

        for value in catalog_filters:
            decoded = unquote(value)
            mark = self._extract_filter_value(decoded, "mark")
            model = self._extract_filter_value(decoded, "model")
            if mark and model:
                model_key = self._slugify(f"{mark}-{model}")
                return f"{self.source}:{model_key}", f"{self._titleize(mark)} {self._titleize(model)}"

        if cars:
            fallback = self._fallback_model_label(cars[0].title)
            model_key = self._slugify(fallback)
            return f"{self.source}:{model_key}", fallback

        return f"{self.source}:unknown", "Unknown model"

    async def _new_context(self, playwright) -> BrowserContext:
        return await playwright.chromium.launch_persistent_context(
            user_data_dir=settings.browser_data_dir,
            headless=settings.headless,
            slow_mo=settings.slow_mo_ms,
            viewport={"width": 1440, "height": 1000},
        )

    async def _accept_region_dialog(self, page: Page) -> None:
        for name in ("Я согласен", "Да", "Хорошо", "Понятно"):
            try:
                await page.get_by_role("button", name=name).click(timeout=2_000)
                return
            except TimeoutError:
                continue

    async def _scroll_results(self, page: Page) -> None:
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(700)

    def _unique_links(self, hrefs: list[str]) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()

        for href in hrefs:
            normalized = self._normalize_url(href)
            if "/cars/used/sale/" not in normalized or normalized in seen:
                continue
            seen.add(normalized)
            links.append(normalized)

        return links

    def _normalize_url(self, href: str) -> str:
        absolute = urljoin("https://auto.ru", href)
        parts = urlsplit(absolute)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _extract_filter_value(self, text: str, name: str) -> str:
        pattern = re.compile(rf"(?:^|,){re.escape(name)}=([^,]+)")
        match = pattern.search(text)
        return match.group(1) if match else ""

    def _slugify(self, value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9а-яё]+", "-", value, flags=re.IGNORECASE)
        return re.sub(r"-+", "-", value).strip("-")

    def _titleize(self, value: str) -> str:
        return value.replace("_", " ").replace("-", " ").strip().title()

    def _fallback_model_label(self, title: str) -> str:
        if not title:
            return "Unknown model"

        candidate = re.split(r"[,\-–—|]", title, maxsplit=1)[0].strip()
        candidate = re.sub(r"\b(19|20)\d{2}\b.*$", "", candidate).strip()
        candidate = candidate or title.split()[0]
        return self._titleize(candidate)

    async def _parse_car_page(self, page: Page, url: str) -> CarDetails:
        await page.goto(url, wait_until="domcontentloaded", timeout=settings.default_timeout_ms)
        await self._accept_region_dialog(page)
        await page.wait_for_timeout(1_000)

        raw_text = await page.locator("body").inner_text(timeout=settings.default_timeout_ms)
        json_ld = await self._read_json_ld(page)
        specs = await self._read_specs(page)

        title = self._first_non_empty(
            await self._text(page, "h1"),
            str(json_ld.get("name", "")),
            self._line_matching(raw_text, r"\b\d{4}\b"),
        )
        price = self._first_non_empty(
            await self._text(page, "[class*='Price']"),
            str(json_ld.get("offers", {}).get("price", "")) if isinstance(json_ld.get("offers"), dict) else "",
            self._line_matching(raw_text, r"\d[\d\s]+[₽Рруб]+"),
        )
        year = self._extract_year(title) or self._extract_year(raw_text)
        mileage = self._line_matching(raw_text, r"\d[\d\s]*(км|km)")
        location = self._line_after_label(raw_text, "Город") or self._line_matching(raw_text, r"Москва|Санкт-Петербург")
        description = await self._text(page, "[class*='Description']")

        return CarDetails(
            url=url,
            source=self.source,
            title=title,
            price=price,
            year=year,
            mileage=mileage,
            location=location,
            specs=specs,
            description=description,
            raw_text=raw_text[:12_000],
        )

    async def _read_json_ld(self, page: Page) -> dict:
        scripts = await page.locator("script[type='application/ld+json']").all_inner_texts()
        for script in scripts:
            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") in {"Product", "Car", "Vehicle"}:
                return data
        return {}

    async def _read_specs(self, page: Page) -> dict[str, str]:
        specs: dict[str, str] = {}
        rows = page.locator("li, [class*='CardInfoRow'], [class*='Complectation']")
        count = min(await rows.count(), 120)

        for index in range(count):
            text = (await rows.nth(index).inner_text()).strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) >= 2 and len(lines[0]) <= 60 and len(lines[1]) <= 120:
                specs.setdefault(lines[0], lines[1])

        return specs

    async def _text(self, page: Page, selector: str) -> str:
        try:
            return (await page.locator(selector).first.inner_text(timeout=2_000)).strip()
        except TimeoutError:
            return ""

    def _first_non_empty(self, *values: str) -> str:
        for value in values:
            value = value.strip()
            if value:
                return value
        return ""

    def _extract_year(self, text: str) -> int | None:
        match = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", text)
        return int(match.group(1)) if match else None

    def _line_matching(self, text: str, pattern: str) -> str:
        regex = re.compile(pattern, re.IGNORECASE)
        for line in text.splitlines():
            line = line.strip()
            if line and regex.search(line):
                return line
        return ""

    def _line_after_label(self, text: str, label: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines[:-1]):
            if line.lower() == label.lower():
                return lines[index + 1]
        return ""
