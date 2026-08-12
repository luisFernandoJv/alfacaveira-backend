# app/repositories/platform/comment_repository.py
"""Repositório de acesso a dados de `Comment`."""

import uuid
from datetime import datetime
from typing import Optional, List

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import selectinload

from app.models.enums import CommentStatus, CommentVoteType
from app.models.platform.comment import Comment, CommentReport, CommentVote
from app.repositories.base import BaseRepository

logger = structlog.get_logger(__name__)

_RELATIONS = (
    selectinload(Comment.user),
    selectinload(Comment.votes),
    selectinload(Comment.reports),
)


class CommentRepository(BaseRepository[Comment]):
    """Repositório de comentários."""

    model = Comment

    async def get_with_relations(self, comment_id: uuid.UUID) -> Comment | None:
        """Busca um comentário com todas as relações carregadas."""
        stmt = (
            select(Comment)
            .where(Comment.id == comment_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(self, comment_id: uuid.UUID, user_id: uuid.UUID) -> Comment | None:
        """Busca um comentário restrito ao dono."""
        stmt = (
            select(Comment)
            .where(Comment.id == comment_id, Comment.user_id == user_id)
            .options(*_RELATIONS)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_question(
        self,
        question_id: uuid.UUID,
        limit: int = 50,
        cursor_id: Optional[uuid.UUID] = None,
        include_replies: bool = True,
    ) -> List[Comment]:
        """Lista comentários de uma questão (apenas principais, não respostas)."""
        try:
            stmt = (
                select(Comment)
                .where(
                    Comment.question_id == question_id,
                    Comment.parent_id.is_(None),
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
                .options(*_RELATIONS)
                .order_by(Comment.upvotes.desc(), Comment.created_at.desc())
                .limit(limit)
            )

            if cursor_id:
                cursor = await self.get_by_id(cursor_id)
                if cursor:
                    stmt = stmt.where(Comment.created_at < cursor.created_at)

            result = await self.session.execute(stmt)
            comments = list(result.scalars().unique().all())

            # 🔥 CORREÇÃO: Carregar replies separadamente, sem atribuir à relação ORM
            if include_replies and comments:
                for comment in comments:
                    replies = await self.list_replies(comment.id)
                    # Armazenar em atributo não-ORM
                    setattr(comment, '_replies', replies)

            return comments
        except Exception as e:
            logger.error("comments.list_by_question_error", question_id=str(question_id), error=str(e))
            return []

    async def list_by_question_with_batch(
        self,
        question_id: uuid.UUID,
        limit: int = 50,
        cursor_id: Optional[uuid.UUID] = None,
        include_replies: bool = True,
    ) -> tuple[List[Comment], int]:
        """🔥 OTIMIZAÇÃO: Lista comentários com batch loading para replies."""
        try:
            # Buscar comentários principais
            stmt = (
                select(Comment)
                .where(
                    Comment.question_id == question_id,
                    Comment.parent_id.is_(None),
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
                .options(*_RELATIONS)
                .order_by(Comment.upvotes.desc(), Comment.created_at.desc())
                .limit(limit)
            )

            if cursor_id:
                cursor = await self.get_by_id(cursor_id)
                if cursor:
                    stmt = stmt.where(Comment.created_at < cursor.created_at)

            result = await self.session.execute(stmt)
            comments = list(result.scalars().unique().all())

            # 🔥 OTIMIZAÇÃO: Batch loading de replies
            if include_replies and comments:
                parent_ids = [c.id for c in comments]
                replies_stmt = (
                    select(Comment)
                    .where(
                        Comment.parent_id.in_(parent_ids),
                        Comment.status == CommentStatus.PUBLICADO,
                        Comment.deleted_at.is_(None),
                    )
                    .options(*_RELATIONS)
                    .order_by(Comment.created_at.asc())
                )
                replies_result = await self.session.execute(replies_stmt)
                replies = list(replies_result.scalars().unique().all())

                # Agrupar replies por parent_id
                replies_by_parent: dict[uuid.UUID, list[Comment]] = {}
                for reply in replies:
                    if reply.parent_id not in replies_by_parent:
                        replies_by_parent[reply.parent_id] = []
                    replies_by_parent[reply.parent_id].append(reply)

                for comment in comments:
                    setattr(comment, '_replies', replies_by_parent.get(comment.id, []))

            total = await self.count_by_question(question_id)
            return comments, total

        except Exception as e:
            logger.error("comments.list_by_question_batch_error", question_id=str(question_id), error=str(e))
            return [], 0

    async def list_replies(self, parent_id: uuid.UUID) -> List[Comment]:
        """Lista respostas de um comentário."""
        try:
            stmt = (
                select(Comment)
                .where(
                    Comment.parent_id == parent_id,
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
                .options(*_RELATIONS)
                .order_by(Comment.created_at.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().unique().all())
        except Exception as e:
            logger.error("comments.list_replies_error", parent_id=str(parent_id), error=str(e))
            return []

    async def count_by_question(self, question_id: uuid.UUID) -> int:
        """Conta comentários de uma questão."""
        try:
            stmt = (
                select(func.count())
                .select_from(Comment)
                .where(
                    Comment.question_id == question_id,
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error("comments.count_by_question_error", question_id=str(question_id), error=str(e))
            return 0

    async def get_vote(self, user_id: uuid.UUID, comment_id: uuid.UUID) -> CommentVote | None:
        """Busca o voto de um usuário em um comentário."""
        stmt = select(CommentVote).where(
            CommentVote.user_id == user_id,
            CommentVote.comment_id == comment_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_vote(
        self,
        user_id: uuid.UUID,
        comment_id: uuid.UUID,
        vote_type: CommentVoteType,
    ) -> CommentVote | None:
        """Cria ou atualiza um voto."""
        existing = await self.get_vote(user_id, comment_id)

        if existing:
            if existing.vote_type == vote_type:
                # Remove o voto (toggle)
                await self.session.delete(existing)
                await self.session.flush()
                await self._update_vote_counts(comment_id)
                return None
            else:
                # Muda o voto
                existing.vote_type = vote_type
                await self.session.flush()
                await self._update_vote_counts(comment_id)
                return existing

        # Novo voto
        vote = CommentVote(
            user_id=user_id,
            comment_id=comment_id,
            vote_type=vote_type,
        )
        self.session.add(vote)
        await self.session.flush()
        await self._update_vote_counts(comment_id)
        return vote

    async def _update_vote_counts(self, comment_id: uuid.UUID) -> None:
        """Atualiza a contagem de votos de um comentário."""
        # Contar upvotes
        up_stmt = select(func.count()).select_from(CommentVote).where(
            CommentVote.comment_id == comment_id,
            CommentVote.vote_type == CommentVoteType.UP,
        )
        up_result = await self.session.execute(up_stmt)
        upvotes = up_result.scalar() or 0

        # Contar downvotes
        down_stmt = select(func.count()).select_from(CommentVote).where(
            CommentVote.comment_id == comment_id,
            CommentVote.vote_type == CommentVoteType.DOWN,
        )
        down_result = await self.session.execute(down_stmt)
        downvotes = down_result.scalar() or 0

        # Atualizar comentário
        stmt = (
            update(Comment)
            .where(Comment.id == comment_id)
            .values(upvotes=upvotes, downvotes=downvotes)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def create_report(
        self,
        user_id: uuid.UUID,
        comment_id: uuid.UUID,
        reason: str,
    ) -> CommentReport:
        """Cria uma denúncia para um comentário."""
        report = CommentReport(
            user_id=user_id,
            comment_id=comment_id,
            reason=reason,
        )
        self.session.add(report)
        await self.session.flush()

        # Incrementar contagem de denúncias
        stmt = (
            update(Comment)
            .where(Comment.id == comment_id)
            .values(report_count=Comment.report_count + 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        return report

    async def get_reports_paginated(
        self,
        limit: int = 50,
        cursor_id: Optional[uuid.UUID] = None,
    ) -> list[CommentReport]:
        """Lista denúncias paginadas."""
        stmt = (
            select(CommentReport)
            .where(CommentReport.resolved_at.is_(None))
            .order_by(CommentReport.created_at.asc())
            .limit(limit)
        )
        if cursor_id:
            cursor = await self.get_by_id(cursor_id)
            if cursor:
                stmt = stmt.where(CommentReport.created_at > cursor.created_at)

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    # ==========================================================================
    # 🔥 NOVOS MÉTODOS PARA P2 — PERFORMANCE
    # ==========================================================================

    async def get_comments_with_pagination(
        self,
        question_id: uuid.UUID,
        limit: int = 20,
        cursor: Optional[uuid.UUID] = None,
    ) -> tuple[List[Comment], bool]:
        """🔥 P2: Paginação cursor-based para virtualização."""
        try:
            stmt = (
                select(Comment)
                .where(
                    Comment.question_id == question_id,
                    Comment.parent_id.is_(None),
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
                .options(*_RELATIONS)
                .order_by(Comment.upvotes.desc(), Comment.created_at.desc())
                .limit(limit + 1)  # Buscar um a mais para saber se há mais
            )

            if cursor:
                stmt = stmt.where(Comment.created_at < cursor)

            result = await self.session.execute(stmt)
            items = list(result.scalars().unique().all())

            has_more = len(items) > limit
            if has_more:
                items = items[:limit]

            # Carregar replies em batch
            if items:
                parent_ids = [c.id for c in items]
                replies_stmt = (
                    select(Comment)
                    .where(
                        Comment.parent_id.in_(parent_ids),
                        Comment.status == CommentStatus.PUBLICADO,
                        Comment.deleted_at.is_(None),
                    )
                    .options(*_RELATIONS)
                    .order_by(Comment.created_at.asc())
                )
                replies_result = await self.session.execute(replies_stmt)
                replies = list(replies_result.scalars().unique().all())

                replies_by_parent: dict[uuid.UUID, list[Comment]] = {}
                for reply in replies:
                    if reply.parent_id not in replies_by_parent:
                        replies_by_parent[reply.parent_id] = []
                    replies_by_parent[reply.parent_id].append(reply)

                for comment in items:
                    setattr(comment, '_replies', replies_by_parent.get(comment.id, []))

            return items, has_more

        except Exception as e:
            logger.error("comments.get_comments_with_pagination_error", question_id=str(question_id), error=str(e))
            return [], False

    async def count_comments_by_question(self, question_id: uuid.UUID) -> int:
        """🔥 P2: Contagem rápida de comentários."""
        try:
            stmt = (
                select(func.count())
                .select_from(Comment)
                .where(
                    Comment.question_id == question_id,
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error("comments.count_comments_by_question_error", question_id=str(question_id), error=str(e))
            return 0

    async def get_replies_batch(self, parent_ids: List[uuid.UUID]) -> dict[uuid.UUID, List[Comment]]:
        """🔥 P2: Busca replies em lote para múltiplos comentários."""
        try:
            if not parent_ids:
                return {}

            stmt = (
                select(Comment)
                .where(
                    Comment.parent_id.in_(parent_ids),
                    Comment.status == CommentStatus.PUBLICADO,
                    Comment.deleted_at.is_(None),
                )
                .options(*_RELATIONS)
                .order_by(Comment.created_at.asc())
            )
            result = await self.session.execute(stmt)
            replies = list(result.scalars().unique().all())

            replies_by_parent: dict[uuid.UUID, list[Comment]] = {}
            for reply in replies:
                if reply.parent_id not in replies_by_parent:
                    replies_by_parent[reply.parent_id] = []
                replies_by_parent[reply.parent_id].append(reply)

            return replies_by_parent

        except Exception as e:
            logger.error("comments.get_replies_batch_error", error=str(e))
            return {}