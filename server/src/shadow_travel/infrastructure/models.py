from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_string() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ShadowUser(Base):
    __tablename__ = "shadow_users"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_shadow_users_issuer_sub"),)

    shadow_user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OIDCLoginFlow(Base):
    __tablename__ = "oidc_login_flows"

    flow_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(255), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    return_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AppSession(Base):
    __tablename__ = "app_sessions"
    __table_args__ = (Index("ix_app_sessions_user_expires", "shadow_user_id", "expires_at"),)

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    shadow_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentIdempotencyKey(Base):
    __tablename__ = "agent_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("agent_id", "operation", "idempotency_key", name="uq_agent_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index(
            "ix_audit_events_resource_created",
            "resource_type",
            "resource_id",
            "created_at",
        ),
    )

    audit_event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_app: Mapped[str | None] = mapped_column(String(64))
    audience: Mapped[str | None] = mapped_column(String(64))
    scope: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, object] | None] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelMap(Base):
    __tablename__ = "travel_maps"
    __table_args__ = (Index("ix_travel_maps_owner_updated", "owner_user_id", "updated_at"),)

    map_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="CN")
    accent: Mapped[str] = mapped_column(String(16), nullable=False, default="#315d4e")
    accent_soft: Mapped[str] = mapped_column(String(16), nullable=False, default="#dfe9e2")
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="行")
    period: Mapped[str | None] = mapped_column(String(120))
    progress_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    progress_target: Mapped[int | None] = mapped_column(Integer)
    progress_start_date: Mapped[date | None] = mapped_column(Date)
    progress_end_date: Mapped[date | None] = mapped_column(Date)
    route_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_map_id: Mapped[str | None] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="SET NULL")
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelMapMember(Base):
    __tablename__ = "travel_map_members"

    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), primary_key=True
    )
    shadow_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelMapInvitation(Base):
    __tablename__ = "travel_map_invitations"
    __table_args__ = (
        Index("ix_travel_map_invitations_map_created", "map_id", "created_at"),
        UniqueConstraint("token_hash", name="uq_travel_map_invitation_token"),
    )

    invitation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="editor")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelPlace(Base):
    __tablename__ = "travel_places"
    __table_args__ = (
        Index("ix_travel_places_owner_updated", "owner_user_id", "updated_at"),
        UniqueConstraint(
            "owner_user_id",
            "provider",
            "provider_place_id",
            name="uq_travel_place_owner_provider",
        ),
    )

    place_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    district: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="CN")
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    coordinate_reference: Mapped[str] = mapped_column(String(16), nullable=False, default="GCJ02")
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    provider_place_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelMapPlace(Base):
    __tablename__ = "travel_map_places"
    __table_args__ = (UniqueConstraint("map_id", "position", name="uq_travel_map_position"),)

    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), primary_key=True
    )
    place_id: Mapped[str] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="地点")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    shared_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    custom_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    counts_toward_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    added_by: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelPlacePreference(Base):
    __tablename__ = "travel_place_preferences"

    map_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    place_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shadow_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), primary_key=True
    )
    preference: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["map_id", "place_id"],
            ["travel_map_places.map_id", "travel_map_places.place_id"],
            ondelete="CASCADE",
        ),
    )


class TravelVisit(Base):
    __tablename__ = "travel_visits"
    __table_args__ = (
        Index("ix_travel_visits_user_date", "shadow_user_id", "visited_on"),
        Index("ix_travel_visits_place_date", "place_id", "visited_on"),
    )

    visit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    place_id: Mapped[str] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="CASCADE"), nullable=False
    )
    shadow_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    source_map_id: Mapped[str | None] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="SET NULL")
    )
    visited_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelVisitMapShare(Base):
    __tablename__ = "travel_visit_map_shares"

    visit_id: Mapped[str] = mapped_column(
        ForeignKey("travel_visits.visit_id", ondelete="CASCADE"), primary_key=True
    )
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), primary_key=True
    )
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelVisitRecord(Base):
    __tablename__ = "travel_visit_records"
    __table_args__ = (
        Index(
            "ix_travel_visit_records_shared_map_created",
            "shared_map_id",
            "visibility",
            "created_at",
        ),
    )

    visit_record_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    visit_id: Mapped[str] = mapped_column(
        ForeignKey("travel_visits.visit_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rating: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    shared_map_id: Mapped[str | None] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelMapFieldDefinition(Base):
    __tablename__ = "travel_map_field_definitions"
    __table_args__ = (
        UniqueConstraint("map_id", "field_key", name="uq_travel_map_field_key"),
        UniqueConstraint("map_id", "position", name="uq_travel_map_field_position"),
    )

    field_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    options: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelRoute(Base):
    __tablename__ = "travel_routes"
    __table_args__ = (Index("ix_travel_routes_map_updated", "map_id", "updated_at"),)

    route_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="walking")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TravelRouteStop(Base):
    __tablename__ = "travel_route_stops"
    __table_args__ = (UniqueConstraint("route_id", "place_id", name="uq_route_stop_place"),)

    route_id: Mapped[str] = mapped_column(
        ForeignKey("travel_routes.route_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_id: Mapped[str] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="CASCADE"), nullable=False
    )


class TravelMediaUploadIntent(Base):
    __tablename__ = "travel_media_upload_intents"
    __table_args__ = (
        Index("ix_travel_media_upload_owner_expires", "owner_user_id", "expires_at"),
        UniqueConstraint("media_upload_id", name="uq_travel_media_upload_id"),
    )

    intent_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    media_upload_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[str] = mapped_column(
        ForeignKey("travel_places.place_id", ondelete="CASCADE"), nullable=False
    )
    visit_id: Mapped[str | None] = mapped_column(
        ForeignKey("travel_visits.visit_id", ondelete="CASCADE")
    )
    caption: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_media_id: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelPhoto(Base):
    __tablename__ = "travel_photos"
    __table_args__ = (
        Index("ix_travel_photos_record_created", "visit_record_id", "created_at"),
        UniqueConstraint("media_id", name="uq_travel_photo_media_id"),
    )

    photo_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    media_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    visit_record_id: Mapped[str] = mapped_column(
        ForeignKey("travel_visit_records.visit_record_id", ondelete="CASCADE"), nullable=False
    )
    caption: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    location_visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    exif_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="strip_all")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelShareLink(Base):
    __tablename__ = "travel_share_links"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_travel_share_link_token"),
        Index("ix_travel_share_links_map_created", "map_id", "created_at"),
    )

    share_link_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    view_state: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    include_shared_records: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TravelAgentMapGrant(Base):
    __tablename__ = "travel_agent_map_grants"

    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_by: Mapped[str] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"), nullable=False
    )
    allow_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_drafts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TravelAgentDraft(Base):
    __tablename__ = "travel_agent_drafts"
    __table_args__ = (Index("ix_travel_agent_drafts_map_status", "map_id", "status", "created_at"),)

    draft_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    map_id: Mapped[str] = mapped_column(
        ForeignKey("travel_maps.map_id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="SET NULL")
    )
    draft_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("shadow_users.shadow_user_id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_resource_type: Mapped[str | None] = mapped_column(String(32))
    applied_resource_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
