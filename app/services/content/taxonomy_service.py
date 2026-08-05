"""Regras de negócio da hierarquia de taxonomia (Disciplina/Assunto/Subassunto)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.content.taxonomy import Discipline, Subject, Topic
from app.repositories.content.taxonomy_repository import (
    DisciplineRepository,
    SubjectRepository,
    TopicRepository,
)


class TaxonomyService:
    def __init__(self, session: AsyncSession) -> None:
        self._disciplines = DisciplineRepository(session)
        self._subjects = SubjectRepository(session)
        self._topics = TopicRepository(session)

    async def list_disciplines(self) -> list[Discipline]:
        return await self._disciplines.list_all()

    async def list_subjects(self, discipline_id: uuid.UUID) -> list[Subject]:
        discipline = await self._disciplines.get_by_id(discipline_id)
        if discipline is None:
            raise NotFoundError("Disciplina não encontrada.")
        return await self._subjects.list_by_discipline(discipline_id)

    async def list_topics(self, subject_id: uuid.UUID) -> list[Topic]:
        subject = await self._subjects.get_by_id(subject_id)
        if subject is None:
            raise NotFoundError("Assunto não encontrado.")
        return await self._topics.list_by_subject(subject_id)
