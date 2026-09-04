import asyncio
import json
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from shadow_travel.infrastructure.models import TravelPlace
from shadow_travel.integrations.maps.base import (
    CoordinateReference,
    GeoPoint,
    MapProviderError,
    MapProviderNotConfigured,
    MapProviderOperationUnavailable,
    ProviderPlace,
    RouteMode,
)
from shadow_travel.integrations.maps.google import (
    GoogleLogPrivacy,
    GoogleMapProvider,
    decode_polyline,
)
from test_travel_lifecycle import ORIGIN, clients, get, post


def test_google_http_log_redacts_keys_and_location_queries():
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        "",
        1,
        "HTTP Request: %s",
        ("https://maps.googleapis.com/maps/api/geocode/json?key=sensitive&address=private",),
        None,
    )
    assert GoogleLogPrivacy().filter(record)
    assert "sensitive" not in record.getMessage()
    assert "address" not in record.getMessage()


def test_google_search_routes_matrix_contracts(tmp_path):
    key = tmp_path / "google.key"
    key.write_text("fixture-only-key")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-Goog-Api-Key"] == "fixture-only-key"
        assert request.headers["X-Goog-FieldMask"] != "*"
        if request.url.path.endswith("searchText"):
            assert json.loads(request.content)["pageSize"] == 20
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "id": "real-id",
                            "displayName": {"text": "Live name"},
                            "location": {"longitude": 2.3, "latitude": 48.8},
                            "addressComponents": [{"types": ["country"], "shortText": "FR"}],
                            "attributions": [
                                {"provider": "Contributor", "providerUri": "https://example.com"}
                            ],
                        }
                    ]
                },
            )
        if request.url.path.endswith("computeRouteMatrix"):
            # Missing and reordered cells must not be interpreted as 0/array-position pairs.
            return httpx.Response(
                200,
                json=[
                    {
                        "originIndex": 1,
                        "destinationIndex": 0,
                        "condition": "ROUTE_EXISTS",
                        "duration": "120s",
                    },
                    {
                        "originIndex": 0,
                        "destinationIndex": 1,
                        "condition": "ROUTE_NOT_FOUND",
                        "status": {"code": 5},
                    },
                ],
            )
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 1000,
                        "duration": "600s",
                        "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GoogleMapProvider(key_file=str(key), client=client)
            found = await provider.search_places("museum", limit=25)
            assert found[0].point.crs == CoordinateReference.WGS84
            assert found[0].attributions[0]["provider"] == "Contributor"
            points = (
                GeoPoint(2.3, 48.8, CoordinateReference.WGS84),
                GeoPoint(2.4, 48.9, CoordinateReference.WGS84),
            )
            route = await provider.route(points, mode=RouteMode.WALKING)
            assert route.duration_seconds == 600
            assert len(route.points) == 3
            matrix = await provider.matrix(points, mode=RouteMode.TRANSIT)
            assert matrix[0]["status"] == "unknown"
            assert matrix[1]["duration_seconds"] is None
            assert matrix[2]["duration_seconds"] == 120
            with pytest.raises(MapProviderOperationUnavailable):
                await provider.route((*points, points[0]), mode=RouteMode.TRANSIT)
            with pytest.raises(ValueError):
                await provider.route(
                    (GeoPoint(1, 2, CoordinateReference.GCJ02), points[0]), mode=RouteMode.WALKING
                )

    asyncio.run(run())
    assert len(calls) == 3
    with pytest.raises(MapProviderError):
        decode_polyline("~~~~")


def test_google_failure_is_sanitized_and_unconfigured_is_not_success():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(403, text="secret server key"))
        ) as client:
            provider = GoogleMapProvider(key_file=None, client=client)
            with pytest.raises(MapProviderNotConfigured):
                await provider.search_places("Paris")
            provider._key = lambda: "fixture"
            with pytest.raises(MapProviderError) as error:
                await provider.search_places("Paris")
            assert "secret" not in str(error.value) and "fixture" not in str(error.value)

    asyncio.run(run())


def test_google_reference_never_persists_provider_content(settings_factory):
    (client, user), *_ = clients(settings_factory)
    app = client.app
    app.state.google.details = AsyncMock(
        return_value=ProviderPlace(
            provider="google",
            provider_place_id="known-id",
            name="Provider secret name",
            address="Provider address",
            country_code="FR",
            point=GeoPoint(2.3, 48.8, CoordinateReference.WGS84),
        )
    )
    saved = post(
        client,
        "maps/google/references",
        {
            "provider_place_id": "known-id",
            "alias": "我的周六晚餐",
            "city": "Paris",
            "country_code": "FR",
        },
    )
    assert saved.status_code == 200, saved.text
    row = saved.json()
    assert row["coordinate"] is None and row["address"] == ""
    assert row["name"] == "我的周六晚餐" and row["countryCode"] == "FR"
    with app.state.database.session_factory() as session:
        entity = session.get(TravelPlace, row["id"])
        assert entity.longitude is None and entity.latitude is None
        assert entity.provider_place_id == "known-id"
    details = get(client, "maps/google/places/known-id")
    assert details.headers["cache-control"] == "private, no-store"
    assert details.json()["name"] == "Provider secret name"
    workspace = get(client, "workspace").text
    assert "Provider secret name" not in workspace and "Provider address" not in workspace
    update = client.patch(
        f"/api/browser/v1/places/{row['id']}",
        headers=ORIGIN,
        json={"longitude": 2.3, "latitude": 48.8},
    )
    assert update.status_code == 422
    assert (
        post(
            client,
            "maps/google/references",
            {"provider_place_id": "known-id", "alias": "my alias", "country_code": "JP"},
        ).status_code
        == 422
    )
