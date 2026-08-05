"""Schemas do contexto 'practice'."""

from app.schemas.practice.question_attempt import (
    AnswerResultResponse,
    AnswerSubmitRequest,
    QuestionAttemptListItem,
)
from app.schemas.practice.training_session import (
    TrainingSessionCreateRequest,
    TrainingSessionDetailResponse,
    TrainingSessionListItem,
    TrainingSessionQuestionResponse,
)

__all__ = [
    "AnswerResultResponse",
    "AnswerSubmitRequest",
    "QuestionAttemptListItem",
    "TrainingSessionCreateRequest",
    "TrainingSessionDetailResponse",
    "TrainingSessionListItem",
    "TrainingSessionQuestionResponse",
]
