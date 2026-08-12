# app/models/platform/comment.py
"""Modelo de comentários e respostas."""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import CommentStatus, CommentVoteType


class Comment(UUIDPKMixin, TimestampMixin, Base):
    """Comentário de um usuário sobre uma questão."""

    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_comment_user_question"),
        Index("ix_comments_question_id_status", "question_id", "status"),
    )

    # Campos do banco de dados
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CommentStatus] = mapped_column(
        PGEnum(
            CommentStatus,
            name="comment_status",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=CommentStatus.PUBLICADO,
        index=True,
    )
    upvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relacionamentos
    user: Mapped["User"] = relationship()
    question: Mapped["Question"] = relationship()

    # 🔥 CORREÇÃO: backref renomeado de "replies" para "child_replies".
    # O código de serviço/router usa um atributo NÃO-ORM chamado `_replies`
    # (populado manualmente via `list_replies()`, para evitar lazy-load
    # assíncrono / MissingGreenlet) e o schema Pydantic `CommentResponse`
    # tem um campo `replies`. Antes, o backref="replies" criava uma
    # relação ORM real chamada `Comment.replies`, que colidia
    # conceitualmente com os dois anteriores e podia ser lazy-carregada
    # acidentalmente fora de um `await`, disparando exceções não tratadas
    # (agora capturadas pelo handler genérico, mas o ideal é eliminar a
    # causa). Renomear remove essa colisão de nomes.
    parent: Mapped["Comment"] = relationship(
        remote_side="Comment.id",
        backref="child_replies",
        single_parent=True,
    )
    votes: Mapped[list["CommentVote"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["CommentReport"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
    )

    # Campos extras NÃO PERSISTIDOS usando ClassVar.
    # Isso evita que o SQLAlchemy tente mapeá-los como colunas.
    user_name: ClassVar[str | None] = None
    user_initials: ClassVar[str | None] = None
    user_vote: ClassVar[str | None] = None
    can_edit: ClassVar[bool] = False
    can_delete: ClassVar[bool] = False
    is_owner: ClassVar[bool] = False


class CommentVote(UUIDPKMixin, Base):
    """Voto de um usuário em um comentário."""

    __tablename__ = "comment_votes"
    __table_args__ = (
        UniqueConstraint("user_id", "comment_id", name="uq_comment_vote_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vote_type: Mapped[CommentVoteType] = mapped_column(
        PGEnum(
            CommentVoteType,
            name="comment_vote_type",
            create_type=False,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    comment: Mapped["Comment"] = relationship(back_populates="votes")


class CommentReport(UUIDPKMixin, Base):
    """Denúncia de um comentário por um usuário."""

    __tablename__ = "comment_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "comment_id", name="uq_comment_report_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    comment: Mapped["Comment"] = relationship(back_populates="reports")