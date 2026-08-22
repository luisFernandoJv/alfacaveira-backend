# app/api/v1/platform/comments.py
"""Endpoints HTTP de comentários."""

import uuid
from typing import Annotated, List

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import CursorPage
from app.core.responses import Envelope, Meta
from app.database.session import get_db
from app.models.content.question import Question
from app.models.identity.user import User
from app.models.platform.comment import Comment
from app.models.enums import CommentStatus
from app.schemas.platform.comment import (
    CommentCreateRequest,
    CommentListResponse,
    CommentModerateRequest,
    CommentReportRequest,
    CommentResponse,
    CommentUpdateRequest,
    CommentVoteRequest,
)
from app.security.dependencies import CurrentAdminUser, CurrentUser
from app.services.platform.comment_service import CommentService

router = APIRouter()
logger = structlog.get_logger(__name__)


def get_comment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CommentService:
    return CommentService(session)


CommentServiceDep = Annotated[CommentService, Depends(get_comment_service)]


# ==================================================================== #
# LEITURA
# ==================================================================== #



@router.get("/community", response_model=Envelope[list[dict]])
async def community_feed(
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=30)] = 8,
    user_id: uuid.UUID | None = None,
) -> Envelope[list[dict]]:
    """Feed público de questões com discussões recentes e respostas."""
    stmt = (
        select(Comment)
        .join(Comment.question)
        .where(
            *( [Comment.user_id == user_id] if user_id else [] ),
            Comment.parent_id.is_(None),
            Comment.status == CommentStatus.PUBLICADO,
            Comment.deleted_at.is_(None),
        )
        .options(
            selectinload(Comment.user).selectinload(User.profile),
            selectinload(Comment.question).selectinload(Question.discipline),
            selectinload(Comment.question).selectinload(Question.exam_board),
        )
        .order_by(Comment.created_at.desc())
        .limit(limit * 2)
    )
    result = await session.execute(stmt)
    seed_comments = list(result.scalars().unique().all())

    seen_questions: set[uuid.UUID] = set()
    feed: list[dict] = []

    for seed in seed_comments:
        if seed.question_id in seen_questions:
            continue
        seen_questions.add(seed.question_id)

        comments, total = await comment_service.list_by_question(
            question_id=seed.question_id,
            user_id=current_user.id,
            limit=4,
        )

        items = []
        for comment in comments:
            comment_dict = {
                "id": comment.id,
                "user_id": comment.user_id,
                "content": comment.content,
                "created_at": comment.created_at,
                "upvotes": comment.upvotes,
                "downvotes": comment.downvotes,
                "user_name": getattr(comment, "user_name", None),
                "user_initials": getattr(comment, "user_initials", None),
                "user_avatar_url": getattr(comment, "user_avatar_url", None),
                "replies": [],
            }
            for reply in getattr(comment, "_replies", [])[:5]:
                comment_dict["replies"].append({
                    "id": reply.id,
                    "user_id": reply.user_id,
                    "content": reply.content,
                    "created_at": reply.created_at,
                    "upvotes": reply.upvotes,
                    "downvotes": reply.downvotes,
                    "user_name": getattr(reply, "user_name", None),
                    "user_initials": getattr(reply, "user_initials", None),
                    "user_avatar_url": getattr(reply, "user_avatar_url", None),
                    "replies": [],
                })
            items.append(comment_dict)

        feed.append({
            "question_id": seed.question_id,
            "question_statement": seed.question.statement,
            "discipline": getattr(seed.question.discipline, "name", None),
            "exam_board": getattr(seed.question.exam_board, "acronym", None),
            "comments": items,
            "total_comments": total,
        })

        if len(feed) >= limit:
            break

    return Envelope(data=feed)


@router.get("/question/{question_id}", response_model=Envelope[CommentListResponse])
async def list_comments(
    question_id: uuid.UUID,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Envelope[CommentListResponse]:
    """Lista comentários de uma questão."""
    page = CursorPage(limit=limit, cursor=cursor)
    decoded_cursor = page.decode_cursor()
    cursor_id = uuid.UUID(decoded_cursor) if decoded_cursor else None

    comments, total = await comment_service.list_by_question(
        question_id=question_id,
        user_id=current_user.id,
        limit=limit,
        cursor_id=cursor_id,
    )

    # 🔥 CORREÇÃO: Construir respostas manualmente para evitar MissingGreenlet
    items = []
    for comment in comments:
        # Converter campos básicos
        comment_dict = {
            "id": comment.id,
            "user_id": comment.user_id,
            "question_id": comment.question_id,
            "parent_id": comment.parent_id,
            "content": comment.content,
            "status": comment.status,
            "upvotes": comment.upvotes,
            "downvotes": comment.downvotes,
            "report_count": comment.report_count,
            "is_edited": comment.is_edited,
            "edited_at": comment.edited_at,
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
            "user_name": getattr(comment, 'user_name', None),
            "user_initials": getattr(comment, 'user_initials', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
            "user_vote": getattr(comment, 'user_vote', None),
            "can_edit": getattr(comment, 'can_edit', False),
            "can_delete": getattr(comment, 'can_delete', False),
            "is_owner": getattr(comment, 'is_owner', False),
            "replies": []
        }
        
        # Adicionar replies se existirem
        if hasattr(comment, '_replies') and comment._replies:
            for reply in comment._replies:
                reply_dict = {
                    "id": reply.id,
                    "user_id": reply.user_id,
                    "question_id": reply.question_id,
                    "parent_id": reply.parent_id,
                    "content": reply.content,
                    "status": reply.status,
                    "upvotes": reply.upvotes,
                    "downvotes": reply.downvotes,
                    "report_count": reply.report_count,
                    "is_edited": reply.is_edited,
                    "edited_at": reply.edited_at,
                    "created_at": reply.created_at,
                    "updated_at": reply.updated_at,
                    "user_name": getattr(reply, 'user_name', None),
                    "user_initials": getattr(reply, 'user_initials', None),
                    "user_avatar_url": getattr(reply, 'user_avatar_url', None),
                    "user_vote": getattr(reply, 'user_vote', None),
                    "can_edit": getattr(reply, 'can_edit', False),
                    "can_delete": getattr(reply, 'can_delete', False),
                    "is_owner": getattr(reply, 'is_owner', False),
                    "replies": []
                }
                comment_dict["replies"].append(CommentResponse(**reply_dict))
        
        items.append(CommentResponse(**comment_dict))

    next_cursor = (
        CursorPage.encode_cursor(str(comments[-1].id)) if len(comments) == limit else None
    )

    return Envelope(
        data=CommentListResponse(
            items=items,
            total=total,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )
    )


@router.get("/{comment_id}", response_model=Envelope[CommentResponse])
async def get_comment(
    comment_id: uuid.UUID,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> Envelope[CommentResponse]:
    """Detalhe de um comentário."""
    comment = await comment_service.get_comment(comment_id, current_user.id)
    
    # 🔥 CORREÇÃO: Converter manualmente para evitar MissingGreenlet
    comment_dict = {
        "id": comment.id,
        "user_id": comment.user_id,
        "question_id": comment.question_id,
        "parent_id": comment.parent_id,
        "content": comment.content,
        "status": comment.status,
        "upvotes": comment.upvotes,
        "downvotes": comment.downvotes,
        "report_count": comment.report_count,
        "is_edited": comment.is_edited,
        "edited_at": comment.edited_at,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "user_name": getattr(comment, 'user_name', None),
        "user_initials": getattr(comment, 'user_initials', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
        "user_vote": getattr(comment, 'user_vote', None),
        "can_edit": getattr(comment, 'can_edit', False),
        "can_delete": getattr(comment, 'can_delete', False),
        "is_owner": getattr(comment, 'is_owner', False),
        "replies": []
    }
    
    return Envelope(data=CommentResponse(**comment_dict))


# ==================================================================== #
# ESCRITA
# ==================================================================== #


@router.post(
    "",
    response_model=Envelope[CommentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    body: CommentCreateRequest,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> Envelope[CommentResponse]:
    """Cria um novo comentário."""
    comment = await comment_service.create_comment(
        user_id=current_user.id,
        data=body,
    )
    
    # 🔥 CORREÇÃO: Converter manualmente para evitar MissingGreenlet
    comment_dict = {
        "id": comment.id,
        "user_id": comment.user_id,
        "question_id": comment.question_id,
        "parent_id": comment.parent_id,
        "content": comment.content,
        "status": comment.status,
        "upvotes": comment.upvotes,
        "downvotes": comment.downvotes,
        "report_count": comment.report_count,
        "is_edited": comment.is_edited,
        "edited_at": comment.edited_at,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "user_name": getattr(comment, 'user_name', None),
        "user_initials": getattr(comment, 'user_initials', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
        "user_vote": getattr(comment, 'user_vote', None),
        "can_edit": getattr(comment, 'can_edit', False),
        "can_delete": getattr(comment, 'can_delete', False),
        "is_owner": getattr(comment, 'is_owner', False),
        "replies": []
    }
    
    return Envelope(data=CommentResponse(**comment_dict))


# app/api/v1/platform/comments.py

@router.put("/{comment_id}", response_model=Envelope[CommentResponse])
async def update_comment(
    comment_id: uuid.UUID,
    body: CommentUpdateRequest,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> Envelope[CommentResponse]:
    """Edita um comentário existente."""
    # 🔥 CORREÇÃO: o try/except aqui capturava QUALQUER exceção (inclusive
    # NotFoundError/ConflictError do domínio) e devolvia
    # `Envelope(data=None, error=None)`. Isso é inválido: o response_model
    # declarado é `Envelope[CommentResponse]`, que exige `data` não-nulo —
    # o FastAPI tentava validar/serializar esse retorno contra o schema e
    # falhava, gerando uma exceção NÃO tratada (sem handler genérico
    # registrado, isso resultava em resposta vazia/corrompida para o
    # cliente). Além disso, engolir o erro escondia falhas reais do
    # usuário (ex: "comentário não encontrado" virava uma resposta "vazia
    # e sem erro"). Agora deixamos a exceção propagar — os handlers em
    # `app/core/exceptions.py` (DomainError + genérico) cuidam de
    # devolver o envelope de erro correto com o status HTTP certo.
    comment = await comment_service.update_comment(
        comment_id=comment_id,
        user_id=current_user.id,
        data=body,
    )

    # Converter manualmente para evitar MissingGreenlet
    comment_dict = {
        "id": comment.id,
        "user_id": comment.user_id,
        "question_id": comment.question_id,
        "parent_id": comment.parent_id,
        "content": comment.content,
        "status": comment.status,
        "upvotes": comment.upvotes,
        "downvotes": comment.downvotes,
        "report_count": comment.report_count,
        "is_edited": comment.is_edited,
        "edited_at": comment.edited_at,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "user_name": getattr(comment, 'user_name', None),
        "user_initials": getattr(comment, 'user_initials', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
        "user_vote": getattr(comment, 'user_vote', None),
        "can_edit": getattr(comment, 'can_edit', False),
        "can_delete": getattr(comment, 'can_delete', False),
        "is_owner": getattr(comment, 'is_owner', False),
        "replies": []
    }

    return Envelope(data=CommentResponse(**comment_dict))


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> None:
    """Deleta (soft delete) um comentário."""
    try:
        await comment_service.delete_comment(
            comment_id=comment_id,
            user_id=current_user.id,
        )
        # 🔥 CORREÇÃO: Retornar None para 204 No Content
        return None
    except Exception:
        logger.exception("comment.delete_failed", comment_id=str(comment_id))
        raise


# ==================================================================== #
# VOTAÇÃO
# ==================================================================== #


@router.post("/{comment_id}/vote", response_model=Envelope[dict])
async def vote_comment(
    comment_id: uuid.UUID,
    body: CommentVoteRequest,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> Envelope[dict]:
    """Vota em um comentário (up/down)."""
    result = await comment_service.vote_comment(
        comment_id=comment_id,
        user_id=current_user.id,
        vote_type=body.vote_type,
    )
    return Envelope(data=result)


# ==================================================================== #
# DENÚNCIA
# ==================================================================== #


@router.post("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_comment(
    comment_id: uuid.UUID,
    body: CommentReportRequest,
    current_user: CurrentUser,
    comment_service: CommentServiceDep,
) -> None:
    """Denuncia um comentário."""
    try:
        await comment_service.report_comment(
            comment_id=comment_id,
            user_id=current_user.id,
            reason=body.reason,
        )
        # 🔥 CORREÇÃO: Retornar None para 204 No Content
        return None
    except Exception:
        logger.exception("comment.report_failed", comment_id=str(comment_id))
        raise


# ==================================================================== #
# MODERAÇÃO (Admin)
# ==================================================================== #


@router.post("/{comment_id}/moderate", response_model=Envelope[CommentResponse])
async def moderate_comment(
    comment_id: uuid.UUID,
    body: CommentModerateRequest,
    current_user: CurrentAdminUser,
    comment_service: CommentServiceDep,
) -> Envelope[CommentResponse]:
    """Ação de moderação em um comentário (apenas admin)."""
    # 🔥 CORREÇÃO P0 (2026-08-12): `action`/`reason` eram parâmetros soltos,
    # interpretados pelo FastAPI como query params — o frontend envia no
    # corpo JSON (padrão igual a vote/report), causando 422. Ver
    # docs/IMPLEMENTATION_LOG.md e ADR-020 em docs/DECISIONS.md.
    comment = await comment_service.moderate_comment(
        comment_id=comment_id,
        admin_user_id=current_user.id,
        action=body.action,
        reason=body.reason,
    )
    
    # 🔥 CORREÇÃO: Converter manualmente para evitar MissingGreenlet
    comment_dict = {
        "id": comment.id,
        "user_id": comment.user_id,
        "question_id": comment.question_id,
        "parent_id": comment.parent_id,
        "content": comment.content,
        "status": comment.status,
        "upvotes": comment.upvotes,
        "downvotes": comment.downvotes,
        "report_count": comment.report_count,
        "is_edited": comment.is_edited,
        "edited_at": comment.edited_at,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "user_name": getattr(comment, 'user_name', None),
        "user_initials": getattr(comment, 'user_initials', None),
            "user_avatar_url": getattr(comment, 'user_avatar_url', None),
        "user_vote": getattr(comment, 'user_vote', None),
        "can_edit": getattr(comment, 'can_edit', False),
        "can_delete": getattr(comment, 'can_delete', False),
        "is_owner": getattr(comment, 'is_owner', False),
        "replies": []
    }
    
    return Envelope(data=CommentResponse(**comment_dict))