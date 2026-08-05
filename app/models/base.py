"""Mixins reutilizáveis entre models.

- UUIDPKMixin: chave primária UUID gerada em Python (uuid4).
- TimestampMixin: created_at / updated_at gerenciados pelo banco.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    """Adiciona coluna `id` (UUID v4) como chave primária."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Adiciona `created_at` e `updated_at` com timezone, geridos pelo banco."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
