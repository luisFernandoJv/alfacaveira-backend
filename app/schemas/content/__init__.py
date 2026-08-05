"""Schemas do contexto 'content'."""

from app.schemas.content.exam_source import (
    ExamBoardResponse,
    ExamEditionResponse,
    OrganizationResponse,
)
from app.schemas.content.question import (
    QuestionAlternativeInput,
    QuestionAlternativeResponse,
    QuestionCreateRequest,
    QuestionDetailResponse,
    QuestionListItem,
    QuestionStatusUpdateRequest,
    QuestionTagResponse,
    QuestionUpdateRequest,
)
from app.schemas.content.taxonomy import DisciplineResponse, SubjectResponse, TopicResponse

__all__ = [
    "DisciplineResponse",
    "ExamBoardResponse",
    "ExamEditionResponse",
    "OrganizationResponse",
    "QuestionAlternativeInput",
    "QuestionAlternativeResponse",
    "QuestionCreateRequest",
    "QuestionDetailResponse",
    "QuestionListItem",
    "QuestionStatusUpdateRequest",
    "QuestionTagResponse",
    "QuestionUpdateRequest",
    "SubjectResponse",
    "TopicResponse",
]
