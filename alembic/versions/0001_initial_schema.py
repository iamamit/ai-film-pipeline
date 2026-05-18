"""Initial schema — 5 tables + pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-05-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension ────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── projects ──────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(50)),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_phase", sa.String(100)),
        sa.Column("estimated_completion", sa.DateTime(timezone=True)),
        sa.Column("total_cost", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # ── workflow_executions ───────────────────────────────────────────────────
    op.create_table(
        "workflow_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.String(255)),
        sa.Column("phase", sa.String(100)),
        sa.Column("status", sa.String(50)),
        sa.Column("input", sa.JSON()),
        sa.Column("output", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_workflow_executions_project_id", "workflow_executions", ["project_id"]
    )

    # ── ai_usage ──────────────────────────────────────────────────────────────
    op.create_table(
        "ai_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50)),
        sa.Column("model", sa.String(100)),
        sa.Column("operation", sa.String(100)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost", sa.Numeric(10, 4)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_usage_project_id", "ai_usage", ["project_id"])

    # ── assets ────────────────────────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(50)),
        sa.Column("scene_number", sa.Integer()),
        sa.Column("storage_url", sa.Text()),
        sa.Column("metadata", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])

    # ── research_chunks (with pgvector embedding column) ──────────────────────
    op.create_table(
        "research_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text()),
        sa.Column("metadata", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_research_chunks_project_id", "research_chunks", ["project_id"])

    # Vector column and IVFFlat index — must use raw DDL (not standard Alembic types)
    op.execute("ALTER TABLE research_chunks ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX ix_research_chunks_embedding "
        "ON research_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("research_chunks")
    op.drop_table("assets")
    op.drop_table("ai_usage")
    op.drop_table("workflow_executions")
    op.drop_table("projects")
    op.execute("DROP EXTENSION IF EXISTS vector")
