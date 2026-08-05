"""Repositórios de acesso a dados da hierarquia de taxonomia.

Disciplina -> Assunto -> Subassunto. Tabelas pequenas (dezenas/centenas de
linhas), então listagem simples ordenada por nome é suficiente — sem
paginação cursor-based aqui (reservada para `Question`, alto volume).
"""

import uuid

from sqlalchemy import select

from app.models.content.taxonomy import Discipline, Subject, Topic
from app.repositories.base import BaseRepository


class DisciplineRepository(BaseRepository[Discipline]):
    model = Discipline

    async def list_all(self) -> list[Discipline]:
        stmt = select(Discipline).order_by(Discipline.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class SubjectRepository(BaseRepository[Subject]):
    model = Subject

    async def list_by_discipline(self, discipline_id: uuid.UUID) -> list[Subject]:
        stmt = (
            select(Subject)
            .where(Subject.discipline_id == discipline_id)
            .order_by(Subject.name.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class TopicRepository(BaseRepository[Topic]):
    model = Topic

    async def list_by_subject(self, subject_id: uuid.UUID) -> list[Topic]:
        stmt = select(Topic).where(Topic.subject_id == subject_id).order_by(Topic.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
