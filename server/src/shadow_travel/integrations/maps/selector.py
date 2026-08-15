from __future__ import annotations

from .base import MapProvider


class MapProviderSelector:
    def __init__(self, *, domestic: MapProvider, international: MapProvider) -> None:
        self._domestic = domestic
        self._international = international

    def for_country(self, country_code: str | None) -> MapProvider:
        return self._domestic if (country_code or "CN").upper() == "CN" else self._international

    def by_id(self, provider_id: str) -> MapProvider:
        providers = {
            self._domestic.provider_id: self._domestic,
            self._international.provider_id: self._international,
        }
        try:
            return providers[provider_id]
        except KeyError as exc:
            raise ValueError(f"unknown map provider: {provider_id}") from exc
