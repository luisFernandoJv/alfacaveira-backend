# app/repositories/platform/question_report_repository.py
from app.models.platform.question_report import QuestionReport
from app.repositories.base import BaseRepository


class QuestionReportRepository(BaseRepository[QuestionReport]):
    """Repositório de reportes de questões."""
    model = QuestionReport