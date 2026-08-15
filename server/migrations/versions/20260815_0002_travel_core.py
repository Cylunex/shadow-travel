"""Create the persistent travel-map core.

Revision ID: 20260815_0002
Revises: 20260815_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0002"
down_revision: str | None = "20260815_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "travel_maps",
        sa.Column("map_id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("subtitle", sa.String(300), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("accent", sa.String(16), nullable=False),
        sa.Column("accent_soft", sa.String(16), nullable=False),
        sa.Column("emoji", sa.String(8), nullable=False),
        sa.Column("period", sa.String(120)),
        sa.Column("route_enabled", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_travel_maps_owner_updated", "travel_maps", ["owner_user_id", "updated_at"])
    op.create_table(
        "travel_map_members",
        sa.Column("map_id", sa.String(36), primary_key=True),
        sa.Column("shadow_user_id", sa.String(36), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shadow_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "travel_places",
        sa.Column("place_id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("short_name", sa.String(80), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("district", sa.String(100), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("coordinate_reference", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("provider_place_id", sa.String(255)),
        sa.Column("recommended", sa.String(300)),
        sa.Column("price", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_user_id", "provider", "provider_place_id", name="uq_travel_place_provider"),
    )
    op.create_index("ix_travel_places_owner_updated", "travel_places", ["owner_user_id", "updated_at"])
    op.create_table(
        "travel_map_places",
        sa.Column("map_id", sa.String(36), primary_key=True),
        sa.Column("place_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_by", sa.String(36), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("map_id", "position", name="uq_travel_map_position"),
    )
    op.create_table(
        "travel_place_preferences",
        sa.Column("place_id", sa.String(36), primary_key=True),
        sa.Column("shadow_user_id", sa.String(36), primary_key=True),
        sa.Column("preference", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shadow_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "travel_visits",
        sa.Column("visit_id", sa.String(36), primary_key=True),
        sa.Column("place_id", sa.String(36), nullable=False),
        sa.Column("shadow_user_id", sa.String(36), nullable=False),
        sa.Column("map_id", sa.String(36)),
        sa.Column("visited_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shadow_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_travel_visits_user_date", "travel_visits", ["shadow_user_id", "visited_on"])
    op.create_index("ix_travel_visits_place_date", "travel_visits", ["place_id", "visited_on"])
    op.create_table(
        "travel_routes",
        sa.Column("route_id", sa.String(36), primary_key=True),
        sa.Column("map_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("distance_meters", sa.Integer()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_travel_routes_map_updated", "travel_routes", ["map_id", "updated_at"])
    op.create_table(
        "travel_route_stops",
        sa.Column("route_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("place_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["travel_routes.route_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_id", "place_id", name="uq_route_stop_place"),
    )


def downgrade() -> None:
    op.drop_table("travel_route_stops")
    op.drop_index("ix_travel_routes_map_updated", table_name="travel_routes")
    op.drop_table("travel_routes")
    op.drop_index("ix_travel_visits_place_date", table_name="travel_visits")
    op.drop_index("ix_travel_visits_user_date", table_name="travel_visits")
    op.drop_table("travel_visits")
    op.drop_table("travel_place_preferences")
    op.drop_table("travel_map_places")
    op.drop_index("ix_travel_places_owner_updated", table_name="travel_places")
    op.drop_table("travel_places")
    op.drop_table("travel_map_members")
    op.drop_index("ix_travel_maps_owner_updated", table_name="travel_maps")
    op.drop_table("travel_maps")
