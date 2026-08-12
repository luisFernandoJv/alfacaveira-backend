# app/services/platform/comment_service.py
"""Regras de negócio de comentários."""

import uuid
from datetime import UTC, datetime
from typing import Optional, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.enums import CommentStatus, CommentVoteType
from app.models.platform.comment import Comment, CommentReport
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.platform.comment_repository import CommentRepository
from app.schemas.platform.comment import CommentCreateRequest, CommentUpdateRequest
from app.services.platform.notification_service import NotificationService

logger = structlog.get_logger(__name__)


class CommentService:
    """Serviço de comentários."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._comments = CommentRepository(session)
        self._questions = QuestionRepository(session)
        self._notification_service = NotificationService(session)

    # ==================================================================== #
    # LEITURA
    # ==================================================================== #

    async def get_comment(self, comment_id: uuid.UUID, user_id: uuid.UUID) -> Comment:
        """Busca um comentário específico."""
        comment = await self._comments.get_with_relations(comment_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado.")
        self._enrich_comment(comment, user_id)
        return comment

    async def list_by_question(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 50,
        cursor_id: Optional[uuid.UUID] = None,
    ) -> tuple[List[Comment], int]:
        """Lista comentários de uma questão."""
        # Verificar se a questão existe
        question = await self._questions.get_by_id(question_id)
        if not question:
            raise NotFoundError("Questão não encontrada.")

        # Buscar comentários principais
        comments = await self._comments.list_by_question(
            question_id=question_id,
            limit=limit,
            cursor_id=cursor_id,
            include_replies=False,
        )

        # Contar total
        total = await self._comments.count_by_question(question_id)

        # Enriquecer cada comentário e carregar replies
        for comment in comments:
            self._enrich_comment(comment, user_id)

            # Carregar replies manualmente
            replies = await self._comments.list_replies(comment.id)
            for reply in replies:
                self._enrich_comment(reply, user_id)

            # Armazenar replies em atributo não-ORM
            setattr(comment, '_replies', replies)

        return comments, total

    def _enrich_comment(self, comment: Comment, user_id: uuid.UUID) -> None:
        """Adiciona metadados ao comentário para o usuário atual."""
        # Verificar se é dono
        comment.is_owner = comment.user_id == user_id

        # Adicionar nome do usuário
        if comment.user:
            comment.user_name = comment.user.full_name
            # Gerar iniciais
            name_parts = comment.user.full_name.split()
            if len(name_parts) >= 2:
                comment.user_initials = f"{name_parts[0][0]}{name_parts[-1][0]}".upper()
            elif name_parts:
                comment.user_initials = name_parts[0][:2].upper()
            else:
                comment.user_initials = "??"
        else:
            comment.user_name = "Usuário"
            comment.user_initials = "??"

        # Verificar se o usuário atual votou
        comment.user_vote = None
        if hasattr(comment, 'votes'):
            for vote in comment.votes:
                if vote.user_id == user_id:
                    comment.user_vote = vote.vote_type.value
                    break

        # Permissões
        comment.can_edit = comment.is_owner and comment.status == CommentStatus.PUBLICADO
        comment.can_delete = comment.is_owner and comment.deleted_at is None

    # ==================================================================== #
    # ESCRITA
    # ==================================================================== #

    async def create_comment(
        self,
        user_id: uuid.UUID,
        data: CommentCreateRequest,
    ) -> Comment:
        """Cria um novo comentário."""
        # Verificar se a questão existe
        question = await self._questions.get_by_id(data.question_id)
        if not question:
            raise NotFoundError("Questão não encontrada.")

        # Verificar se o pai existe (se for resposta)
        if data.parent_id:
            parent = await self._comments.get_by_id(data.parent_id)
            if not parent or parent.question_id != data.question_id:
                raise NotFoundError("Comentário pai não encontrado.")

        # Verificar se o usuário já comentou nesta questão
        if not data.parent_id:
            stmt = select(Comment).where(
                Comment.user_id == user_id,
                Comment.question_id == data.question_id,
                Comment.parent_id.is_(None),
                Comment.status == CommentStatus.PUBLICADO,
                Comment.deleted_at.is_(None),
            )
            result = await self._session.execute(stmt)
            if result.scalar_one_or_none():
                raise ConflictError("Você já comentou nesta questão.")

        comment = Comment(
            user_id=user_id,
            question_id=data.question_id,
            parent_id=data.parent_id,
            content=data.content,
            status=CommentStatus.PUBLICADO,
        )

        async with UnitOfWork(self._session):
            await self._comments.add(comment)
            await self._session.flush()

        # 🔥 NOTIFICAÇÃO: Notificar autor da questão sobre novo comentário
        # Erros aqui NUNCA devem bloquear a criação do comentário, que já
        # foi persistida e commitada acima. `logger.exception` grava o
        # stacktrace completo (em vez de `print`, que não aparece de forma
        # confiável em produção nem é estruturado para agregação de logs).
        try:
            if not data.parent_id and question.created_by and question.created_by != user_id:
                await self._notification_service.notify_new_comment(
                    question_id=data.question_id,
                    comment_id=comment.id,
                    comment_author_id=user_id,
                    question_author_id=question.created_by,
                    comment_content=comment.content,
                )

            # 🔥 NOTIFICAÇÃO: Notificar autor do comentário pai sobre nova resposta
            if data.parent_id:
                parent_comment = await self._comments.get_by_id(data.parent_id)
                if parent_comment and parent_comment.user_id != user_id:
                    await self._notification_service.notify_new_reply(
                        parent_comment_id=data.parent_id,
                        reply_id=comment.id,
                        reply_author_id=user_id,
                        parent_author_id=parent_comment.user_id,
                        reply_content=comment.content,
                    )
        except Exception:
            # Log completo do erro (com traceback), mas não bloqueia a
            # criação do comentário — o comentário já foi persistido.
            logger.exception(
                "comment.notification_failed",
                comment_id=str(comment.id),
                question_id=str(data.question_id),
            )

        # Recarregar com relações
        return await self._comments.get_with_relations(comment.id)

    async def update_comment(
        self,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
        data: CommentUpdateRequest,
    ) -> Comment:
        """Edita um comentário existente."""
        comment = await self._comments.get_owned(comment_id, user_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado ou não é seu.")

        if comment.deleted_at:
            raise ConflictError("Este comentário foi deletado.")

        if comment.status != CommentStatus.PUBLICADO:
            raise ConflictError("Este comentário não pode ser editado.")

        # Atualizar o conteúdo
        comment.content = data.content
        comment.is_edited = True
        comment.edited_at = datetime.now(UTC)

        async with UnitOfWork(self._session):
            await self._session.flush()
            await self._session.refresh(comment)

        # Recarregar com todas as relações
        return await self._comments.get_with_relations(comment.id)

    async def delete_comment(
        self,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Deleta (soft delete) um comentário."""
        comment = await self._comments.get_owned(comment_id, user_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado ou não é seu.")

        comment.deleted_at = datetime.now(UTC)

        async with UnitOfWork(self._session):
            await self._session.flush()

    async def vote_comment(
        self,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
        vote_type: str,
    ) -> dict:
        """Vota em um comentário."""
        comment = await self._comments.get_by_id(comment_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado.")

        if comment.user_id == user_id:
            raise ForbiddenError("Você não pode votar no seu próprio comentário.")

        vote_enum = CommentVoteType.UP if vote_type == "up" else CommentVoteType.DOWN

        async with UnitOfWork(self._session):
            vote = await self._comments.upsert_vote(
                user_id=user_id,
                comment_id=comment_id,
                vote_type=vote_enum,
            )
            await self._session.flush()

        # 🔥 NOTIFICAÇÃO: Notificar autor do comentário sobre o voto
        try:
            if comment.user_id != user_id:
                await self._notification_service.notify_comment_vote(
                    comment_id=comment_id,
                    voter_id=user_id,
                    comment_author_id=comment.user_id,
                    vote_type=vote_type,
                )
        except Exception:
            logger.exception(
                "comment.vote_notification_failed",
                comment_id=str(comment.id),
            )

        # Buscar comentário atualizado
        updated = await self._comments.get_by_id(comment_id)

        return {
            "upvotes": updated.upvotes,
            "downvotes": updated.downvotes,
            "user_vote": vote_type if vote else None,
        }

    # ==================================================================== #
    # DENÚNCIA E MODERAÇÃO
    # ==================================================================== #

    async def report_comment(
        self,
        comment_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> None:
        """Denuncia um comentário."""
        comment = await self._comments.get_by_id(comment_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado.")

        if comment.user_id == user_id:
            raise ForbiddenError("Você não pode denunciar seu próprio comentário.")

        # Verificar se já denunciou
        stmt = select(CommentReport).where(
            CommentReport.user_id == user_id,
            CommentReport.comment_id == comment_id,
        )
        result = await self._session.execute(stmt)
        if result.scalar_one_or_none():
            raise ConflictError("Você já denunciou este comentário.")

        async with UnitOfWork(self._session):
            await self._comments.create_report(user_id, comment_id, reason)
            await self._session.flush()

    async def moderate_comment(
        self,
        comment_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        action: str,
        reason: str | None = None,
    ) -> Comment:
        """Ação de moderação em um comentário."""
        comment = await self._comments.get_with_relations(comment_id)
        if not comment:
            raise NotFoundError("Comentário não encontrado.")

        if action == "remove":
            comment.status = CommentStatus.REMOVIDO
            comment.deleted_at = datetime.now(UTC)
        elif action == "block":
            comment.status = CommentStatus.BLOQUEADO
            comment.deleted_at = datetime.now(UTC)
        elif action == "restore":
            comment.status = CommentStatus.PUBLICADO
            comment.deleted_at = None
        else:
            raise ValueError(f"Ação inválida: {action}")

        async with UnitOfWork(self._session):
            await self._session.flush()
            await self._session.refresh(comment)

        return comment