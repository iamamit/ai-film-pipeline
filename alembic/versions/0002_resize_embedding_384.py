"""resize embedding vector from 1536 to 384 (all-MiniLM-L6-v2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE research_chunks ADD COLUMN embedding vector(384)")
    op.execute(
        "CREATE INDEX ix_research_chunks_embedding_384 "
        "ON research_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_research_chunks_embedding_384")
    op.execute("ALTER TABLE research_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE research_chunks ADD COLUMN embedding vector(1536)")
