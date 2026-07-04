from abc import ABC, abstractmethod

from models.car import CarDetails


class ListingProvider(ABC):
    source: str

    @abstractmethod
    async def get_listing_links(self, search_url: str, limit: int | None = None) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def get_car_details(self, links: list[str]) -> list[CarDetails]:
        raise NotImplementedError

    @abstractmethod
    def get_model_identity(self, search_url: str, cars: list[CarDetails]) -> tuple[str, str]:
        raise NotImplementedError
