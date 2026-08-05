"""Origem da questão: banca examinadora, órgão e edição do concurso."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ExamBoard(UUIDPKMixin, TimestampMixin, Base):
    """Banca examinadora (ex.: CEBRASPE, FGV, VUNESP)."""

    __tablename__ = "exam_boards"

    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    acronym: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)


class Organization(UUIDPKMixin, TimestampMixin, Base):
    """Órgão que realiza o concurso (ex.: Polícia Federal, PM/SP)."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    acronym: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(210), unique=True, nullable=False)


class ExamEdition(UUIDPKMixin, TimestampMixin, Base):
    """Edição específica de um concurso (órgão + banca + ano)."""

    __tablename__ = "exam_editions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    exam_board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_boards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(270), unique=True, nullable=False)

    organization: Mapped["Organization"] = relationship()
    exam_board: Mapped["ExamBoard"] = relationship()
