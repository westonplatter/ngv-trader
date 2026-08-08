"""add flexquery_tokens and account token fk

Creates the table that holds IBKR FlexQuery tokens encrypted at rest, and gives
``accounts`` a nullable foreign key recording which token an account was
discovered under.

``token_encrypted`` is declared here as ``sa.Text`` rather than the application's
``src.db_types.EncryptedString``: the ciphertext is urlsafe-base64 ASCII, and a
migration should not import application code that may later be refactored. The
encryption itself is applied by the model, not by the database.

Additive only — no backfill. ``accounts.flex_query_token_id`` stays null until a
sync run stamps it.

Revision ID: 2b1bd1430647
Revises: 701c3434b8dc
Create Date: 2026-08-07 23:10:47.384396

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b1bd1430647"
down_revision: Union[str, Sequence[str], None] = "701c3434b8dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACCOUNT_FK_NAME = "fk_accounts_flex_query_token_id"
ACCOUNT_INDEX_NAME = "ix_accounts_flex_query_token_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "flexquery_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("accounts", sa.Column("flex_query_token_id", sa.Integer(), nullable=True))
    op.create_index(ACCOUNT_INDEX_NAME, "accounts", ["flex_query_token_id"], unique=False)
    op.create_foreign_key(
        ACCOUNT_FK_NAME,
        "accounts",
        "flexquery_tokens",
        ["flex_query_token_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(ACCOUNT_FK_NAME, "accounts", type_="foreignkey")
    op.drop_index(ACCOUNT_INDEX_NAME, table_name="accounts")
    op.drop_column("accounts", "flex_query_token_id")
    op.drop_table("flexquery_tokens")
