from urllib.parse import urlparse

from providers.autoru_provider import AutoRuProvider
from providers.base import ListingProvider


def get_provider(search_url: str) -> ListingProvider | None:
    host = urlparse(search_url).netloc.lower()

    if host.endswith("auto.ru"):
        return AutoRuProvider()

    return None
