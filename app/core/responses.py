"""Envelope padrão de resposta da API: {data, meta, error}."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    """Metadados de paginação/contexto, quando aplicável."""

    next_cursor: str | None = None
    has_more: bool | None = None
    total: int | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta | None = None
    error: None = None


def error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"data": None, "meta": None, "error": {"code": code, "message": message}}
