"""Endpoints públicos de taxonomia — alimentam os filtros do frontend."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.content import DisciplineResponse, SubjectResponse, TopicResponse
from app.services.content import TaxonomyService

router = APIRouter()


def get_taxonomy_service(session: Annotated[AsyncSession, Depends(get_db)]) -> TaxonomyService:
    return TaxonomyService(session)


TaxonomyServiceDep = Annotated[TaxonomyService, Depends(get_taxonomy_service)]


@router.get("/disciplines", response_model=Envelope[list[DisciplineResponse]])
async def list_disciplines(
    taxonomy_service: TaxonomyServiceDep,
) -> Envelope[list[DisciplineResponse]]:
    disciplines = await taxonomy_service.list_disciplines()
    return Envelope(data=[DisciplineResponse.model_validate(d) for d in disciplines])


@router.get("/disciplines/{discipline_id}/subjects", response_model=Envelope[list[SubjectResponse]])
async def list_subjects(
    discipline_id: uuid.UUID, taxonomy_service: TaxonomyServiceDep
) -> Envelope[list[SubjectResponse]]:
    subjects = await taxonomy_service.list_subjects(discipline_id)
    return Envelope(data=[SubjectResponse.model_validate(s) for s in subjects])


@router.get("/subjects/{subject_id}/topics", response_model=Envelope[list[TopicResponse]])
async def list_topics(
    subject_id: uuid.UUID, taxonomy_service: TaxonomyServiceDep
) -> Envelope[list[TopicResponse]]:
    topics = await taxonomy_service.list_topics(subject_id)
    return Envelope(data=[TopicResponse.model_validate(t) for t in topics])
