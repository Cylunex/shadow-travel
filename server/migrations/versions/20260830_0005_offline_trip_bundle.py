"""Add offline-safe Trip and Visit identities plus public location controls.

Revision ID: 20260830_0005
Revises: 20260820_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "travel_trips",
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_map_id", sa.String(length=36), nullable=True),
        sa.Column("client_record_id", sa.String(length=128), nullable=False),
        sa.Column("client_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="planned"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_map_id"], ["travel_maps.map_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("trip_id"),
        sa.UniqueConstraint(
            "owner_user_id", "client_record_id", name="uq_travel_trip_owner_client_record"
        ),
    )
    op.create_index("ix_travel_trips_owner_updated", "travel_trips", ["owner_user_id", "updated_at"])

    op.create_table(
        "travel_client_mutations",
        sa.Column("mutation_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["shadow_users.shadow_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mutation_id"),
        sa.UniqueConstraint(
            "owner_user_id", "operation", "idempotency_key", name="uq_travel_client_mutation"
        ),
    )
    op.create_index(
        "ix_travel_client_mutations_owner_created",
        "travel_client_mutations",
        ["owner_user_id", "created_at"],
    )

    with op.batch_alter_table("travel_map_places") as batch_op:
        batch_op.add_column(
            sa.Column(
                "public_location_precision",
                sa.String(length=16),
                nullable=False,
                server_default="approximate",
            )
        )
        batch_op.add_column(
            sa.Column("privacy_zone", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table("travel_visits") as batch_op:
        batch_op.add_column(sa.Column("trip_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("client_record_id", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("client_payload_hash", sa.String(length=64), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_foreign_key(
            "fk_travel_visits_trip_id", "travel_trips", ["trip_id"], ["trip_id"], ondelete="SET NULL"
        )
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT visit_id FROM travel_visits")).all()
    for (visit_id,) in rows:
        connection.execute(
            sa.text("UPDATE travel_visits SET client_record_id = :value WHERE visit_id = :visit_id"),
            {"value": visit_id, "visit_id": visit_id},
        )
    with op.batch_alter_table("travel_visits") as batch_op:
        batch_op.alter_column("client_record_id", existing_type=sa.String(length=128), nullable=False)
        batch_op.create_unique_constraint(
            "uq_travel_visit_user_client_record", ["shadow_user_id", "client_record_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("travel_visits") as batch_op:
        batch_op.drop_constraint("uq_travel_visit_user_client_record", type_="unique")
        batch_op.drop_constraint("fk_travel_visits_trip_id", type_="foreignkey")
        batch_op.drop_column("version")
        batch_op.drop_column("client_payload_hash")
        batch_op.drop_column("client_record_id")
        batch_op.drop_column("trip_id")
    with op.batch_alter_table("travel_map_places") as batch_op:
        batch_op.drop_column("privacy_zone")
        batch_op.drop_column("public_location_precision")
    op.drop_index("ix_travel_client_mutations_owner_created", table_name="travel_client_mutations")
    op.drop_table("travel_client_mutations")
    op.drop_index("ix_travel_trips_owner_updated", table_name="travel_trips")
    op.drop_table("travel_trips")
