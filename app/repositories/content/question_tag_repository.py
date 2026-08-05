"""Repositório de acesso a dados de `QuestionTag`."""

import uuid

from sqlalchemy import select

from app.models.content.question_tag import QuestionTag
from app.repositories.base import BaseRepository


class QuestionTagRepository(BaseRepository[QuestionTag]):
    model = QuestionTag

    async def list_all(self) -> list[QuestionTag]:
        stmt = select(QuestionTag).order_by(QuestionTag.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, tag_ids: list[uuid.UUID]) -> list[QuestionTag]:
        if not tag_ids:
            return []
        stmt = select(QuestionTag).where(QuestionTag.id.in_(tag_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
