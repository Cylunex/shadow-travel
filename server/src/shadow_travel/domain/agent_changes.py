"""Small, closed command vocabulary. Evidence is data, never executable instructions."""

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from shadow_travel.domain.plan_v2 import Reservation, Stop, StrictModel


class TripFields(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1, max_length=64)
    status: Literal["planned", "active", "completed", "cancelled"] = "planned"

    @model_validator(mode="after")
    def valid_trip(self):
        self.title = self.title.strip()
        if not self.title or self.start_date > self.end_date:
            raise ValueError("invalid title or trip period")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("agent trips are limited to 366 days")
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("invalid IANA timezone") from None
        return self


class CreateTrip(StrictModel):
    op: Literal["CREATE_TRIP"]
    trip: TripFields


class UpdateTrip(StrictModel):
    op: Literal["UPDATE_TRIP"]
    trip: TripFields


class AddStop(StrictModel):
    op: Literal["ADD_STOP"]
    stop: Stop


class MoveStop(StrictModel):
    op: Literal["MOVE_STOP"]
    stop_id: str = Field(min_length=1, max_length=80)
    day: date
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(min_length=1, max_length=64)
    fold: Literal[0, 1] | None = None


class RemoveStop(StrictModel):
    op: Literal["REMOVE_STOP"]
    stop_id: str = Field(min_length=1, max_length=80)


class UpsertReservation(StrictModel):
    op: Literal["UPSERT_RESERVATION"]
    reservation: Reservation


class RemoveReservation(StrictModel):
    op: Literal["REMOVE_RESERVATION"]
    reservation_id: str = Field(min_length=1, max_length=80)


Operation = Annotated[
    CreateTrip
    | UpdateTrip
    | AddStop
    | MoveStop
    | RemoveStop
    | UpsertReservation
    | RemoveReservation,
    Field(discriminator="op"),
]


class Proposal(StrictModel):
    grant_id: str = Field(min_length=1, max_length=36)
    trip_id: str | None = Field(default=None, max_length=36)
    expected_trip_version: int = Field(ge=0)
    expected_plan_revision: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=500)
    operations: list[Operation] = Field(min_length=1, max_length=50)
    inferred: list[str] = Field(default_factory=list, max_length=20)
    uncertainties: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def structure(self):
        if any(len(s) > 500 for s in [*self.inferred, *self.uncertainties]):
            raise ValueError("annotation too long")
        creates = [o for o in self.operations if o.op == "CREATE_TRIP"]
        updates = [o for o in self.operations if o.op == "UPDATE_TRIP"]
        if self.trip_id is None:
            if (
                len(creates) != 1
                or self.operations[0].op != "CREATE_TRIP"
                or updates
                or self.expected_trip_version
                or self.expected_plan_revision
            ):
                raise ValueError("new trip requires one leading CREATE_TRIP and zero versions")
        elif creates or len(updates) > 1 or self.expected_trip_version < 1:
            raise ValueError("existing trip requires its version; no CREATE_TRIP")
        return self


class ReviewDecision(StrictModel):
    expected_revision: int = Field(ge=1)
    changeset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewEdit(StrictModel):
    expected_revision: int = Field(ge=1)
    proposal: Proposal


class ReviewView(StrictModel):
    protocol: Literal["shadow.travel.review.v2"]
    review_id: str
    reference: str
    agent_id: str
    trip_id: str | None
    state: Literal["pending", "committed", "rejected", "conflicted", "expired"]
    revision: int
    changeset_hash: str
    summary: str
    proposal: Proposal
    preview: dict
    result: dict | None
    created_at: datetime
    expires_at: datetime
    confirmation_mode: Literal["travel_browser_session"]
    direct_domain_write: Literal[False]
    replayed: bool = False
