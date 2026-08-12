# app/services/platform/comment_cache_service.py
"""Serviço de cache para comentários populares."""

import json
import uuid
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.models.platform.comment import Comment
from app.repositories.platform.comment_repository import CommentRepository

logger = structlog.get_logger(__name__)

CACHE_TTL = 300  # 5 minutos


class CommentCacheService:
    """Serviço de cache para comentários de questões populares."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._comments = CommentRepository(session)
        self._cache = get_cache()

    async def get_comments_with_cache(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 50,
        cursor_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[Comment], int]:
        """Busca comentários com cache para questões populares."""
        cache_key = f"comments:question:{question_id}:limit:{limit}:cursor:{cursor_id}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                logger.debug("comments.cache_hit", question_id=str(question_id))
                # Deserializar comentários (implementar serialização adequada)
                return cached, len(cached)

        logger.debug("comments.cache_miss", question_id=str(question_id))
        comments, total = await self._comments.list_by_question(
            question_id=question_id,
            user_id=user_id,
            limit=limit,
            cursor_id=cursor_id,
            include_replies=True,
        )

        if self._cache and comments:
            await self._cache.set(cache_key, comments, ttl=CACHE_TTL)

        return comments, total

    async def invalidate_question_cache(self, question_id: uuid.UUID) -> None:
        """Invalida o cache de uma questão após novo comentário."""
        if not self._cache:
            return

        await self._cache.clear_pattern(f"comments:question:{question_id}:*")
        logger.info("comments.cache_invalidated", question_id=str(question_id))