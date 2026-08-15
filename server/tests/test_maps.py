from __future__ import annotations

import asyncio

import httpx
import pytest

from shadow_travel.integrations.maps.amap import AMapProvider
from shadow_travel.integrations.maps.base import CoordinateReference, GeoPoint, RouteMode
from shadow_travel.integrations.maps.google import GoogleMapProvider
from shadow_travel.integrations.maps.selector import MapProviderSelector


def test_provider_selection_keeps_business_code_provider_neutral() -> None:
    domestic = AMapProvider(key_file=None)
    international = GoogleMapProvider(key_file=None)
    selector = MapProviderSelector(domestic=domestic, international=international)

    assert selector.for_country("CN").provider_id == "amap"
    assert selector.for_country("FR").provider_id == "google"
    assert selector.by_id("amap") is domestic
    asyncio.run(domestic.aclose())


def test_amap_search_returns_explicit_gcj02_points(tmp_path) -> None:
    key_file = tmp_path / "amap.key"
    key_file.write_text("test-amap-key", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/place/text"
        assert request.url.params["key"] == "test-amap-key"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": "poi-1",
                        "name": "示例公园",
                        "location": "116.397,39.908",
                        "address": "示例路",
                        "pname": "北京市",
                        "cityname": "北京市",
                        "adname": "东城区",
                    }
                ],
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://restapi.amap.com", transport=httpx.MockTransport(handler)
        ) as client:
            provider = AMapProvider(key_file=str(key_file), client=client)
            places = await provider.search_places("公园")
        assert places[0].provider == "amap"
        assert places[0].point.crs is CoordinateReference.GCJ02

    asyncio.run(run())


def test_amap_rejects_implicit_coordinate_conversion() -> None:
    provider = AMapProvider(key_file=None)
    place_point = GeoPoint(116.397, 39.908, CoordinateReference.WGS84)

    with pytest.raises(ValueError, match="GCJ-02"):
        provider._require_native(place_point)

    asyncio.run(provider.aclose())


def test_amap_properties_file_and_signature_are_supported(tmp_path) -> None:
    key_file = tmp_path / "amap.properties"
    key_file.write_text("key=test-amap-key\nprivate_key=signature-secret\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-amap-key"
        assert len(request.url.params["sig"]) == 32
        return httpx.Response(200, json={"status": "1", "pois": []})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://restapi.amap.com", transport=httpx.MockTransport(handler)
        ) as client:
            provider = AMapProvider(key_file=str(key_file), client=client)
            assert await provider.search_places("公园") == ()

    asyncio.run(run())


def test_amap_walking_route_uses_v5_endpoint(tmp_path) -> None:
    key_file = tmp_path / "amap.key"
    key_file.write_text("test-amap-key", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v5/direction/walking"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {"paths": [{"distance": "1200", "cost": {"duration": "900"}}]},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://restapi.amap.com", transport=httpx.MockTransport(handler)
        ) as client:
            provider = AMapProvider(key_file=str(key_file), client=client)
            route = await provider.route(
                (
                    GeoPoint(116.397, 39.908, CoordinateReference.GCJ02),
                    GeoPoint(116.407, 39.918, CoordinateReference.GCJ02),
                ),
                mode=RouteMode.WALKING,
            )
        assert route.distance_meters == 1200
        assert route.duration_seconds == 900

    asyncio.run(run())
