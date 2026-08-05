"""Declarative Base compartilhada por todos os models SQLAlchemy."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarativa. Todo model do sistema herda desta classe."""
