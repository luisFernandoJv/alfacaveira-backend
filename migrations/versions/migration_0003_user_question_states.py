"""add user_question_states table

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_question_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("personal_note", sa.Text(), nullable=True),
        sa.Column(
            "noted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "question_id", name="uq_user_question_state"),
    )

    # Índice parcial — favoritas por usuário
    op.execute(
        """
        CREATE INDEX ix_uqs_favorites
            ON user_question_states (user_id)
            WHERE is_favorite = true
        """
    )

    # Índice parcial — questões anotadas por usuário
    op.execute(
        """
        CREATE INDEX ix_uqs_noted
            ON user_question_states (user_id)
            WHERE personal_note IS NOT NULL
        """
    )

    # Trigger para manter updated_at sincronizado
    op.execute(
        """
        CREATE TRIGGER trg_user_question_states_updated_at
            BEFORE UPDATE ON user_question_states
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_user_question_states_updated_at ON user_question_states")
    op.drop_index("ix_uqs_noted", table_name="user_question_states")
    op.drop_index("ix_uqs_favorites", table_name="user_question_states")
    op.drop_table("user_question_states")