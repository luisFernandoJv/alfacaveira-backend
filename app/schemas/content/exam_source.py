"""Schemas de resposta de banca examinadora, órgão e edição de concurso."""

import uuid

from pydantic import BaseModel, ConfigDict


class ExamBoardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    acronym: str
    slug: str


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    acronym: str
    slug: str


class ExamEditionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    exam_board_id: uuid.UUID
    year: int
    name: str
    slug: str
