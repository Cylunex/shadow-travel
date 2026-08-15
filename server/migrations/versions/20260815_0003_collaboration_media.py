"""Add collaboration invitations and Travel-owned media references.

Revision ID: 20260815_0003
Revises: 20260815_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0003"
down_revision: str | None = "20260815_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "travel_map_invitations",
        sa.Column("invitation_id", sa.String(length=36), nullable=False),
        sa.Column("map_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", sa.String(length=36), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by"], ["shadow_users.shadow_user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("invitation_id"),
        sa.UniqueConstraint("token_hash", name="uq_travel_map_invitation_token"),
    )
    op.create_index(
        "ix_travel_map_invitations_map_created",
        "travel_map_invitations",
        ["map_id", "created_at"],
    )

    op.create_table(
        "travel_media_upload_intents",
        sa.Column("intent_id", sa.String(length=36), nullable=False),
        sa.Column("media_upload_id", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("map_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("visit_id", sa.String(length=36), nullable=True),
        sa.Column("caption", sa.String(length=500), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visit_id"], ["travel_visits.visit_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.UniqueConstraint("media_upload_id", name="uq_travel_media_upload_id"),
    )
    op.create_index(
        "ix_travel_media_upload_owner_expires",
        "travel_media_upload_intents",
        ["owner_user_id", "expires_at"],
    )

    op.create_table(
        "travel_photos",
        sa.Column("photo_id", sa.String(length=36), nullable=False),
        sa.Column("media_id", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("map_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=36), nullable=False),
        sa.Column("visit_id", sa.String(length=36), nullable=True),
        sa.Column("caption", sa.String(length=500), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("location_visibility", sa.String(length=16), nullable=False),
        sa.Column("exif_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["travel_places.place_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visit_id"], ["travel_visits.visit_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("photo_id"),
        sa.UniqueConstraint("media_id", name="uq_travel_photo_media_id"),
    )
    op.create_index("ix_travel_photos_place_created", "travel_photos", ["place_id", "created_at"])
    op.create_index("ix_travel_photos_visit_created", "travel_photos", ["visit_id", "created_at"])

    op.create_table(
        "travel_agent_map_grants",
        sa.Column("map_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.String(length=36), nullable=False),
        sa.Column("allow_read", sa.Boolean(), nullable=False),
        sa.Column("allow_drafts", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["granted_by"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("map_id", "agent_id"),
    )
    op.create_table(
        "travel_agent_drafts",
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("map_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("draft_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_resource_type", sa.String(length=32), nullable=True),
        sa.Column("applied_resource_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["travel_maps.map_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["shadow_users.shadow_user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["shadow_users.shadow_user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("draft_id"),
    )
    op.create_index(
        "ix_travel_agent_drafts_map_status",
        "travel_agent_drafts",
        ["map_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_travel_agent_drafts_map_status", table_name="travel_agent_drafts")
    op.drop_table("travel_agent_drafts")
    op.drop_table("travel_agent_map_grants")
    op.drop_index("ix_travel_photos_visit_created", table_name="travel_photos")
    op.drop_index("ix_travel_photos_place_created", table_name="travel_photos")
    op.drop_table("travel_photos")
    op.drop_index("ix_travel_media_upload_owner_expires", table_name="travel_media_upload_intents")
    op.drop_table("travel_media_upload_intents")
    op.drop_index("ix_travel_map_invitations_map_created", table_name="travel_map_invitations")
    op.drop_table("travel_map_invitations")
