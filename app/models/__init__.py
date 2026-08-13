# app/models/__init__.py
"""Agrega todos os models para que Base.metadata os conheça (uso pelo Alembic)."""

from app.models.analytics import StudyStreak, UserDailyStat, UserSubjectStat
from app.models.assessment import ExamAttempt, ExamAttemptQuestion, ExamTemplate
from app.models.billing import Feature, Payment, Plan, PlanFeature, Subscription, SubscriptionHistory
from app.models.content import (
    Discipline,
    ExamBoard,
    ExamEdition,
    Organization,
    Question,
    QuestionAlternative,
    QuestionAttachment,
    QuestionRevision,
    QuestionTag,
    Subject,
    Topic,
)
from app.models.identity import RefreshToken, User, UserProfile
from app.models.learning import Flashcard, FlashcardReview
from app.models.learning.notebook import Notebook
from app.models.learning.notebook_folder import NotebookFolder
from app.models.learning.notebook_question import NotebookQuestion
from app.models.learning.notebook_tag import NotebookTag
from app.models.platform import AdminAuditLog, Notification
from app.models.practice import QuestionAttempt, TrainingSession, TrainingSessionQuestion, UserQuestionState

__all__ = [
    "User",
    "UserProfile",
    "RefreshToken",
    "Discipline",
    "Subject",
    "Topic",
    "ExamBoard",
    "Organization",
    "ExamEdition",
    "Question",
    "QuestionAlternative",
    "QuestionAttachment",
    "QuestionRevision",
    "QuestionTag",
    "TrainingSession",
    "TrainingSessionQuestion",
    "QuestionAttempt",
    "UserQuestionState",
    "ExamTemplate",
    "ExamAttempt",
    "ExamAttemptQuestion",
    "Flashcard",
    "FlashcardReview",
    "UserDailyStat",
    "UserSubjectStat",
    "StudyStreak",
    "Plan",
    "PlanFeature",
    "Feature",
    "Subscription",
    "SubscriptionHistory",
    "Payment",
    "Notification",
    "AdminAuditLog",
    "Notebook",
    "NotebookFolder",
    "NotebookQuestion",
    "NotebookTag",
]