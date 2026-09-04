"""Allow source-only places without fabricating persistent provider coordinates."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0008"
down_revision = "20260904_0007"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("travel_places") as batch:
        batch.alter_column("longitude", existing_type=sa.Float(), nullable=True)
        batch.alter_column("latitude", existing_type=sa.Float(), nullable=True)


def downgrade():
    # A rollback must not invent coordinates or delete saved references.
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT COUNT(*) FROM travel_places WHERE longitude IS NULL OR latitude IS NULL")
    ).scalar():
        raise RuntimeError("Source-only places exist; export/migrate them before downgrade")
    with op.batch_alter_table("travel_places") as batch:
        batch.alter_column("longitude", existing_type=sa.Float(), nullable=False)
        batch.alter_column("latitude", existing_type=sa.Float(), nullable=False)
