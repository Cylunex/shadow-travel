from __future__ import annotations

from fastapi.testclient import TestClient

from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import Base
from shadow_travel.integrations.maps import (
    CoordinateReference,
    GeoPoint,
    ProviderPlace,
    RouteMode,
    RoutePlan,
)
from shadow_travel.main import create_app


class FakeProvider:
    provider_id = "fake-map"
    native_crs = CoordinateReference.GCJ02

    async def search_places(self, query: str, **_: object) -> tuple[ProviderPlace, ...]:
        return (
            ProviderPlace(
                provider=self.provider_id,
                provider_place_id="poi-1",
                name=query,
                point=GeoPoint(116.397, 39.908, self.native_crs),
                address="示例地址",
                country_code="CN",
                city="北京市",
            ),
        )

    async def reverse_geocode(self, point: GeoPoint) -> ProviderPlace:
        return ProviderPlace(
            provider=self.provider_id,
            provider_place_id=None,
            name="地图选点",
            point=point,
            address="示例地址",
            country_code="CN",
        )

    async def route(self, stops: tuple[GeoPoint, ...], *, mode: RouteMode) -> RoutePlan:
        return RoutePlan(
            provider=self.provider_id,
            mode=mode,
            points=stops,
            distance_meters=1200,
            duration_seconds=900,
        )


class FakeSelector:
    def __init__(self) -> None:
        self.provider = FakeProvider()

    def for_country(self, _country_code: str):  # type: ignore[no-untyped-def]
        return self.provider


def _client(settings_factory) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    app.state.maps = FakeSelector()
    app.dependency_overrides[current_browser_user] = lambda: AuthenticatedUser(
        shadow_user_id="user-1",
        issuer="https://auth.example.com",
        subject="subject-1",
        username="traveler",
        display_name="Traveler",
        email="traveler@example.com",
    )
    return TestClient(app)


def test_browser_map_search_and_reverse_geocode(settings_factory) -> None:
    with _client(settings_factory) as client:
        search = client.get("/api/browser/v1/maps/places?query=天坛&region=北京")
        reverse = client.get(
            "/api/browser/v1/maps/reverse-geocode?longitude=116.397&latitude=39.908"
        )

    assert search.status_code == 200
    assert search.json()["places"][0]["name"] == "天坛"
    assert search.json()["places"][0]["coordinate_reference"] == "GCJ02"
    assert reverse.status_code == 200
    assert reverse.json()["place"]["name"] == "地图选点"


def test_browser_route_endpoint_is_provider_neutral(settings_factory) -> None:
    with _client(settings_factory) as client:
        response = client.post(
            "/api/browser/v1/maps/routes",
            headers={"Origin": "http://testserver"},
            json={
                "country_code": "CN",
                "mode": "walking",
                "stops": [
                    {
                        "longitude": 116.397,
                        "latitude": 39.908,
                        "coordinate_reference": "GCJ02",
                    },
                    {
                        "longitude": 116.407,
                        "latitude": 39.918,
                        "coordinate_reference": "GCJ02",
                    },
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["provider"] == "fake-map"
    assert response.json()["distance_meters"] == 1200


def test_browser_capabilities_expose_only_safe_feature_flags(settings_factory) -> None:
    with _client(settings_factory) as client:
        response = client.get("/api/browser/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "media": False,
        "llm": False,
        "international_maps": False,
    }
