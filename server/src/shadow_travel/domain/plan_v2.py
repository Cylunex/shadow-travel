"""Versioned plan values; provider responses and actual visits never live here."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stop(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    place_id: str
    day: date
    start: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    travel_minutes: int | None = Field(default=None, ge=0, le=2880)
    mode: Literal["walking", "transit", "driving", "bicycling"] = "walking"
    anchor: bool = False
    note: str = Field(default="", max_length=2000)
    timezone: str | None = Field(default=None, max_length=64)
    fold: Literal[0, 1] | None = None
    reservation_refs: list[str] = Field(default_factory=list, max_length=20)


class Segment(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    from_stop_id: str
    to_stop_id: str
    mode: Literal["walking", "transit", "driving", "bicycling"] = "walking"
    # User estimates only. Live provider metrics are intentionally not persisted in plans.
    manual_minutes: int | None = Field(default=None, ge=0, le=2880)
    note: str = Field(default="", max_length=2000)


class Reservation(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    day: date
    time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    kind: Literal["stay", "transport", "ticket", "other"] = "other"
    note: str = Field(default="", max_length=2000)
    source_ref: str | None = Field(
        default=None, pattern=r"^shadow://(?:asset|archive|ledger)/", max_length=500
    )
    reference_verification: Literal["unverified"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    fold: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def mark_external_reference_unverified(self):
        if self.source_ref:
            self.reference_verification = "unverified"
        elif self.reference_verification is not None:
            raise ValueError("reference_verification requires source_ref")
        return self


class Task(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    done: bool = False
    due: date | None = None
    assignee: str | None = None


class CandidateMetadata(StrictModel):
    priority: Literal["optional", "normal", "must"] = "normal"
    reason: str = Field(default="", max_length=2000)
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    alternate_group: str | None = Field(default=None, max_length=80)


class PlanDocument(StrictModel):
    schema_version: Literal[1, 2] = 1
    timezone: str | None = Field(default=None, max_length=64)
    candidates: list[str] = Field(default_factory=list, max_length=300)
    candidate_metadata: dict[str, CandidateMetadata] = Field(default_factory=dict, max_length=300)
    stops: list[Stop] = Field(default_factory=list, max_length=300)
    segments: list[Segment] = Field(default_factory=list, max_length=300)
    reservations: list[Reservation] = Field(default_factory=list, max_length=100)
    tasks: list[Task] = Field(default_factory=list, max_length=200)
    budget: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    constraints: str = Field(default="", max_length=4000)
    migration_notes: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def references(self):
        for rows in (self.stops, self.segments, self.reservations, self.tasks):
            if len({r.id for r in rows}) != len(rows):
                raise ValueError("duplicate entity IDs")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("duplicate candidates")
        if set(self.candidate_metadata) - set(self.candidates):
            raise ValueError("candidate metadata must reference candidates")
        if any(s.place_id not in self.candidates for s in self.stops):
            raise ValueError("stops must reference candidates")
        stops = {s.id: s for s in self.stops}
        pairs = set()
        for seg in self.segments:
            if (
                seg.from_stop_id not in stops
                or seg.to_stop_id not in stops
                or seg.from_stop_id == seg.to_stop_id
            ):
                raise ValueError("invalid segment endpoints")
            pair = (seg.from_stop_id, seg.to_stop_id)
            if pair in pairs:
                raise ValueError("duplicate segment")
            pairs.add(pair)
        reservations = {r.id for r in self.reservations}
        if any(set(s.reservation_refs) - reservations for s in self.stops):
            raise ValueError("unknown reservation reference")
        for zone in [
            self.timezone,
            *(s.timezone for s in self.stops),
            *(r.timezone for r in self.reservations),
        ]:
            if zone:
                try:
                    ZoneInfo(zone)
                except (ZoneInfoNotFoundError, ValueError):
                    raise ValueError("invalid_timezone") from None
        if self.schema_version == 1 and self.segments:
            raise ValueError("segments require schema version 2")
        if self.schema_version == 2 and any(s.travel_minutes is not None for s in self.stops):
            raise ValueError("v2 travel estimates belong to segments")
        return self


def instant(day, clock, timezone, fold=None):
    """Reject gaps and require disambiguation of repeated local wall-clock times."""
    naive = datetime.fromisoformat(f"{day}T{clock}")
    zone = ZoneInfo(timezone)
    options = []
    for f in (0, 1):
        value = naive.replace(tzinfo=zone, fold=f).astimezone(UTC)
        if value.astimezone(zone).replace(tzinfo=None) == naive:
            options.append((f, value))
    if not options:
        raise ValueError("nonexistent_local_time")
    if len({v for _, v in options}) > 1 and fold is None:
        raise ValueError("ambiguous_local_time")
    return next(v for f, v in options if fold is None or f == fold)


def check_plan(document, trip):
    errors, warnings = [], []
    rows = []
    for stop in document.stops:
        if (trip.start_date and stop.day < trip.start_date) or (
            trip.end_date and stop.day > trip.end_date
        ):
            errors.append({"id": stop.id, "code": "outside_trip", "message": "安排超出旅程日期"})
        try:
            at = instant(
                stop.day, stop.start, stop.timezone or document.timezone or trip.timezone, stop.fold
            )
            rows.append((at, stop))
        except ValueError as exc:
            errors.append(
                {
                    "id": stop.id,
                    "code": str(exc),
                    "message": "当地时间不存在或重复，请检查时区并选择夏令时偏移",
                }
            )
    rows.sort(key=lambda row: (row[0], row[1].id))
    edges = {(a[1].id, b[1].id) for a, b in zip(rows, rows[1:], strict=False)}
    for segment in document.segments:
        if (segment.from_stop_id, segment.to_stop_id) not in edges:
            errors.append(
                {
                    "id": segment.id,
                    "code": "nonadjacent_segment",
                    "message": "路段端点不是实际时间顺序中的相邻站次，请核对时区和路段",
                }
            )
    for reservation in document.reservations:
        if (trip.start_date and reservation.day < trip.start_date) or (
            trip.end_date and reservation.day > trip.end_date
        ):
            errors.append(
                {"id": reservation.id, "code": "outside_trip", "message": "预约超出旅程日期"}
            )
        try:
            instant(
                reservation.day,
                reservation.time,
                reservation.timezone or document.timezone or trip.timezone,
                reservation.fold,
            )
        except ValueError as exc:
            errors.append(
                {
                    "id": reservation.id,
                    "code": str(exc),
                    "message": "预订当地时间不存在或重复，请检查时区",
                }
            )
    for i, (at, stop) in enumerate(rows):
        next_row = rows[i + 1] if i + 1 < len(rows) else None
        seg = next(
            (
                s
                for s in document.segments
                if next_row and s.from_stop_id == stop.id and s.to_stop_id == next_row[1].id
            ),
            None,
        )
        travel = (
            stop.travel_minutes
            if document.schema_version == 1
            else (seg.manual_minutes if seg else None)
        )
        if travel is None and (next_row or document.schema_version == 1):
            warnings.append(
                {"id": stop.id, "code": "travel_unknown", "message": "交通时间未核验；不是 0 分钟"}
            )
        if next_row and next_row[0] < at + timedelta(minutes=stop.duration_minutes + (travel or 0)):
            errors.append(
                {"id": next_row[1].id, "code": "overlap", "message": "与上一站停留或交通时间冲突"}
            )
    if rows:
        warnings.append(
            {
                "code": "opening_unverified",
                "message": "营业时间、天气和无障碍未核验；计划不保证可通行",
            }
        )
    return {"errors": errors, "warnings": warnings}


def upgrade(document):
    doc = PlanDocument.model_validate(document).model_copy(deep=True)
    if doc.schema_version == 2:
        return doc
    try:
        ordered = sorted(
            doc.stops,
            key=lambda s: (
                instant(s.day, s.start, s.timezone or doc.timezone or "UTC", s.fold),
                s.id,
            ),
        )
    except ValueError:
        # No inferred target when DST ambiguity makes the original chronology uncertain.
        ordered = []
        for stop in doc.stops:
            if stop.travel_minutes is not None:
                doc.migration_notes.append(
                    f"站次 {stop.id} 原出站估计 {stop.travel_minutes} 分钟：时区待核对，未自动连线"
                )
            stop.travel_minutes = None
    for i, stop in enumerate(ordered):
        after = ordered[i + 1] if i + 1 < len(ordered) else None
        if after and instant(
            after.day, after.start, after.timezone or doc.timezone or "UTC", after.fold
        ) > instant(stop.day, stop.start, stop.timezone or doc.timezone or "UTC", stop.fold):
            doc.segments.append(
                Segment(
                    id=f"{stop.id}:{after.id}"[:160],
                    from_stop_id=stop.id,
                    to_stop_id=after.id,
                    mode=stop.mode,
                    manual_minutes=stop.travel_minutes,
                )
            )
        elif stop.travel_minutes is not None:
            doc.migration_notes.append(
                f"站次 {stop.id} 原出站估计 {stop.travel_minutes} 分钟：目标不明确，请手工核对"
            )
        stop.travel_minutes = None
    doc.schema_version = 2
    return doc
