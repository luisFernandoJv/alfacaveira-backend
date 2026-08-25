"""Adiciona categorias e preferências ao sistema de notificações.

Revision ID: 0027_add_notification_category_and_preferences
Revises: 0026_add_question_teacher_name
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0027_add_notification_category_and_preferences"
down_revision: str | None = "0026_add_question_teacher_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATION_CATEGORIES = (
    "comment",
    "billing",
    "plan",
    "marketing",
    "system",
)


def upgrade() -> None:
    category_enum = postgresql.ENUM(
        *_NOTIFICATION_CATEGORIES,
        name="notification_category",
    )
    category_enum.create(op.get_bind(), checkfirst=True)

    # Adiciona nullable primeiro para permitir backfill seguro.
    op.add_column(
        "notifications",
        sa.Column(
            "category",
            postgresql.ENUM(
                *_NOTIFICATION_CATEGORIES,
                name="notification_category",
                create_type=False,
            ),
            nullable=True,
        ),
    )

    # Compatibilidade com notificações antigas. Chaves desconhecidas ficam
    # como system em vez de bloquear o upgrade.
    op.execute(
        sa.text(
            """
            UPDATE notifications
            SET category = CASE
                WHEN type IN ('new_comment', 'new_reply', 'comment_vote', 'mention')
                    THEN 'comment'::notification_category
                WHEN type LIKE 'payment_%'
                  OR type LIKE 'renewal_%'
                  OR type LIKE 'dunning_%'
                  OR type IN ('cancellation', 'reactivation')
                    THEN 'billing'::notification_category
                WHEN type IN ('plan_change', 'plan_granted', 'plan_revoked')
                    THEN 'plan'::notification_category
                WHEN type = 'marketing'
                    THEN 'marketing'::notification_category
                ELSE 'system'::notification_category
            END
            """
        )
    )
    op.alter_column(
        "notifications",
        "category",
        nullable=False,
        server_default=sa.text("'system'::notification_category"),
    )
    op.create_index(
        "ix_notifications_user_category_created_at",
        "notifications",
        ["user_id", "category", "created_at"],
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                *_NOTIFICATION_CATEGORIES,
                name="notification_category",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "category",
            name="uq_notification_preferences_user_category",
        ),
    )
    op.create_index(
        "ix_notification_preferences_user_id",
        "notification_preferences",
        ["user_id"],
    )

    # Não é necessário pré-criar as 5 linhas para cada usuário: o service
    # materializa defaults sob demanda e normaliza categorias mandatórias.
    op.alter_column(
        "notification_preferences",
        "in_app_enabled",
        server_default=None,
    )
    op.alter_column(
        "notification_preferences",
        "email_enabled",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_preferences_user_id",
        table_name="notification_preferences",
    )
    op.drop_table("notification_preferences")
    op.drop_index(
        "ix_notifications_user_category_created_at",
        table_name="notifications",
    )
    op.drop_column("notifications", "category")

    postgresql.ENUM(
        *_NOTIFICATION_CATEGORIES,
        name="notification_category",
    ).drop(op.get_bind(), checkfirst=True)
