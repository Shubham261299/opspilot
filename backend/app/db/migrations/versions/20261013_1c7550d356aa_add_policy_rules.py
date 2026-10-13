"""add policy rules

Revision ID: 1c7550d356aa
Revises: 3ef82e1308c8
Create Date: 2026-10-13 12:16:25.335016
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "1c7550d356aa"
down_revision: str | None = "3ef82e1308c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'stock_register', 'customers', 'outstanding_dues', 'sales_history', "
    "'whatsapp_chat', 'supplier_invoice'"
)
NEW_KINDS = OLD_KINDS + ", 'company_policy'"


def upgrade() -> None:
    # Added by hand: the pgvector extension adds the `vector` column type to this database.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("section_no", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_policy_rules_upload_id_uploads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_rules")),
        sa.UniqueConstraint("code", name=op.f("uq_policy_rules_code")),
    )
    # No vector index: with a few dozen rules an exact scan is instant and always correct.
    # (An HNSW index would only pay off at thousands of rows, and makes results approximate.)
    # Added by hand: autogenerate doesn't detect changed CHECK constraints.
    _set_upload_kinds(NEW_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM uploads WHERE kind = 'company_policy'")
    _set_upload_kinds(OLD_KINDS)
    op.drop_table("policy_rules")
    # The extension is left installed: other tables of a later migration may use it.


def _set_upload_kinds(kinds: str) -> None:
    op.drop_constraint(op.f("ck_uploads_kind_valid"), "uploads", type_="check")
    op.create_check_constraint(op.f("ck_uploads_kind_valid"), "uploads", f"kind IN ({kinds})")
