"""Add capture, private experiences and versioned trip planning; preserve legacy tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0006"
down_revision = "20260830_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "travel_trip_members",
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("travel_trips.trip_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
    )
    op.create_table(
        "travel_plans",
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("travel_trips.trip_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("approved_revision", sa.Integer),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "travel_plan_versions",
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("travel_trips.trip_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column(
            "approved_by",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "travel_captures",
        sa.Column("capture_id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "place_id", sa.String(36), sa.ForeignKey("travel_places.place_id", ondelete="SET NULL")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_capture_owner_created", "travel_captures", ["owner_user_id", "created_at"])
    op.create_table(
        "travel_experiences",
        sa.Column("experience_id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trip_id", sa.String(36), sa.ForeignKey("travel_trips.trip_id", ondelete="SET NULL")
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("occurred_on", sa.Date, nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_experience_owner_trip", "travel_experiences", ["owner_user_id", "trip_id"])


def downgrade():
    for table in (
        "travel_experiences",
        "travel_captures",
        "travel_plan_versions",
        "travel_plans",
        "travel_trip_members",
    ):
        op.drop_table(table)
