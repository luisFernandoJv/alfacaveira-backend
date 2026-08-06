"""Cria a tabela password_reset_tokens (recuperação de senha).

Revision ID: 0002_password_reset_tokens
Revises: 0001_initial_schema
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_password_reset_tokens"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""CREATE TABLE password_reset_tokens (
	user_id UUID NOT NULL,
	token_hash VARCHAR(255) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	UNIQUE (token_hash)
)""")
    op.execute(
        """CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id)"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_tokens CASCADE")
