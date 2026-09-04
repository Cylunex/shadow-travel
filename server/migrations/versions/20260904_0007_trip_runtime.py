"""Member-scoped station outcomes; additive and independent of historical plans."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0007"
down_revision = "20260904_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "travel_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("travel_trips.trip_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("bindings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "travel_stop_outcomes",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("travel_runs.run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stop_id", sa.String(80), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("shadow_users.shadow_user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column(
            "visit_id", sa.String(36), sa.ForeignKey("travel_visits.visit_id", ondelete="SET NULL")
        ),
        sa.Column("actual_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("travel_stop_outcomes")
    op.drop_table("travel_runs")
