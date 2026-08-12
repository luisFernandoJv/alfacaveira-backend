# app/schemas/platform/comment.py
"""Schemas de request/response de comentários."""

import uuid
from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import CommentStatus


class CommentVoteRequest(BaseModel):
    """Request para votar em um comentário."""

    vote_type: str = Field(description="'up' ou 'down'")


class CommentReportRequest(BaseModel):
    """Request para denunciar um comentário."""

    reason: str = Field(min_length=1, max_length=500, description="Motivo da denúncia")


class CommentModerateRequest(BaseModel):
    """Request para ação de moderação em um comentário (admin).

    🔥 CORREÇÃO P0 (2026-08-12): antes desse schema, `action`/`reason` eram
    parâmetros soltos na assinatura do endpoint, o que o FastAPI interpreta
    como query params. O frontend sempre enviou `{ action }` no corpo JSON,
    causando 422 (campo obrigatório ausente na query). Ver ADR-020 em
    docs/DECISIONS.md e docs/IMPLEMENTATION_LOG.md.
    """

    action: str = Field(description="'remove', 'block' ou 'restore'")
    reason: str | None = Field(
        default=None, max_length=500, description="Motivo da ação de moderação"
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"remove", "block", "restore"}
        if v not in allowed:
            raise ValueError(f"Ação inválida: {v}. Deve ser uma de {sorted(allowed)}")
        return v


class CommentCreateRequest(BaseModel):
    """Request para criar um comentário."""

    question_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("O conteúdo não pode estar vazio")
        return v.strip()


class CommentUpdateRequest(BaseModel):
    """Request para editar um comentário."""

    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("O conteúdo não pode estar vazio")
        return v.strip()


class CommentResponse(BaseModel):
    """Resposta de um comentário."""
    
    model_config = ConfigDict(
        from_attributes=True,
        # 🔥 CORREÇÃO CRÍTICA: Ignorar atributos não declarados
        extra="ignore"
    )

    id: uuid.UUID
    user_id: uuid.UUID
    question_id: uuid.UUID
    parent_id: uuid.UUID | None
    content: str
    status: CommentStatus
    upvotes: int
    downvotes: int
    report_count: int
    is_edited: bool
    edited_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # Campos extras que serão preenchidos pelo serviço
    user_name: str | None = Field(default=None, description="Nome do usuário")
    user_initials: str | None = Field(default=None, description="Iniciais do usuário")
    user_vote: str | None = Field(default=None, description="Voto do usuário atual")
    can_edit: bool = Field(default=False, description="Se o usuário atual pode editar")
    can_delete: bool = Field(default=False, description="Se o usuário atual pode deletar")
    is_owner: bool = Field(default=False, description="Se o usuário atual é o dono")
    
    # 🔥 CORREÇÃO: replies não é um campo ORM
    # Será populado manualmente, não via validação automática
    replies: List["CommentResponse"] = Field(
        default_factory=list,
        description="Respostas (carregadas separadamente)"
    )


class CommentListResponse(BaseModel):
    """Lista paginada de comentários."""

    items: list[CommentResponse]
    total: int
    next_cursor: str | None = None
    has_more: bool = False


# Necessário para referências recursivas
CommentResponse.model_rebuild()