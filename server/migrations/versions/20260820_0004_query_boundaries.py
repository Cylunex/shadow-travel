"""Scope provider identities and add timeline query indexes.

Revision ID: 20260820_0004
Revises: 20260815_0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0004"
down_revision: str | None = "20260815_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("travel_places") as batch_op:
        batch_op.drop_constraint("uq_travel_place_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_travel_place_owner_provider",
            ["owner_user_id", "provider", "provider_place_id"],
        )
    op.create_index(
        "ix_travel_visit_records_shared_map_created",
        "travel_visit_records",
        ["shared_map_id", "visibility", "created_at"],
    )
    op.create_index(
        "ix_audit_events_resource_created",
        "audit_events",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource_created", table_name="audit_events")
    op.drop_index(
        "ix_travel_visit_records_shared_map_created",
        table_name="travel_visit_records",
    )
    with op.batch_alter_table("travel_places") as batch_op:
        batch_op.drop_constraint("uq_travel_place_owner_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_travel_place_provider",
            ["provider", "provider_place_id"],
        )
