"""Schemas de resposta da hierarquia de taxonomia (Disciplina/Assunto/Subassunto)."""

import uuid

from pydantic import BaseModel, ConfigDict


class DisciplineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class SubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    discipline_id: uuid.UUID
    name: str
    slug: str


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    name: str
    slug: str
