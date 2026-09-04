"""Transaction-neutral commands. Authentication belongs to the caller, ownership does not."""

from fastapi import HTTPException
from sqlalchemy import select

from shadow_travel.infrastructure.models import TravelTrip


def owned_trip(session, trip_id, owner_id, *, lock=False):
    query = select(TravelTrip).where(
        TravelTrip.trip_id == trip_id, TravelTrip.owner_user_id == owner_id
    )
    trip = session.scalar(query.with_for_update() if lock else query)
    if trip is None:
        raise HTTPException(404, detail={"code": "travel_trip_not_found"})
    return trip


def create_trip_record(session, owner_id, values, client_record_id, request_hash):
    trip = TravelTrip(
        owner_user_id=owner_id,
        client_record_id=client_record_id,
        client_payload_hash=request_hash,
        **values,
    )
    session.add(trip)
    session.flush()
    return trip


def update_trip_record(session, trip, values, expected_version):
    if trip.version != expected_version:
        raise HTTPException(409, detail={"code": "travel_trip_version_conflict"})
    start, end = values.get("start_date", trip.start_date), values.get("end_date", trip.end_date)
    if start and end and start > end:
        raise HTTPException(422, detail={"code": "invalid_trip_period"})
    for name, value in values.items():
        setattr(trip, name, value.strip() if isinstance(value, str) else value)
    trip.version += 1
    session.flush()
    return trip
