"""Agrega todos os models para que Base.metadata os conheça (uso pelo Alembic).

Importar este módulo garante que toda tabela do sistema seja registrada em
`Base.metadata` antes de `alembic revision --autogenerate` rodar.
"""

from app.models.analytics import StudyStreak, UserDailyStat, UserSubjectStat
from app.models.assessment import ExamAttempt, ExamAttemptQuestion, ExamTemplate
from app.models.billing import Payment, Plan, Subscription
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
from app.models.identity import PasswordResetToken, RefreshToken, User, UserProfile
from app.models.learning import Flashcard, FlashcardReview
from app.models.platform import AdminAuditLog, Notification
from app.models.practice import QuestionAttempt, TrainingSession, TrainingSessionQuestion

__all__ = [
    "User",
    "UserProfile",
    "RefreshToken",
    "PasswordResetToken",
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
    "ExamTemplate",
    "ExamAttempt",
    "ExamAttemptQuestion",
    "Flashcard",
    "FlashcardReview",
    "UserDailyStat",
    "UserSubjectStat",
    "StudyStreak",
    "Plan",
    "Subscription",
    "Payment",
    "Notification",
    "AdminAuditLog",
]