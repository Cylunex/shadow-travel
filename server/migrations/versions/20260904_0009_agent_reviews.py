"""Owner-scoped grants and immutable, typed review revisions; no legacy grant escalation."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0009"
down_revision = "20260904_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "travel_agent_resource_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column(
            "trip_id", sa.String(36), sa.ForeignKey("travel_trips.trip_id", ondelete="CASCADE")
        ),
        sa.Column("allow_read", sa.Boolean(), nullable=False),
        sa.Column("allow_propose", sa.Boolean(), nullable=False),
        sa.Column("allow_reservations", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_travel_agent_resource_grants_agent_id", "travel_agent_resource_grants", ["agent_id"]
    )
    op.create_table(
        "travel_agent_reviews",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grant_id",
            sa.String(36),
            sa.ForeignKey("travel_agent_resource_grants.grant_id"),
            nullable=False,
        ),
        sa.Column("trip_id", sa.String(36)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "idempotency_key", name="uq_agent_review_key"),
    )
    op.create_index(
        "ix_agent_review_owner_state",
        "travel_agent_reviews",
        ["owner_user_id", "state", "created_at"],
    )
    op.create_table(
        "travel_agent_review_revisions",
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("travel_agent_reviews.review_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("proposal", sa.JSON(), nullable=False),
        sa.Column("changeset_hash", sa.String(64), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("travel_agent_review_revisions")
    op.drop_table("travel_agent_reviews")
    op.drop_table("travel_agent_resource_grants")
