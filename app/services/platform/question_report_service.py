# app/services/platform/question_report_service.py
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.platform.question_report import QuestionReport
from app.repositories.content.question_repository import QuestionRepository
from app.repositories.platform.question_report_repository import (
    QuestionReportRepository,
)
from app.schemas.platform.question_report import QuestionReportCreateRequest


class QuestionReportService:
    """Serviço de reporte de problemas em questões."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._report_repo = QuestionReportRepository(session)
        self._question_repo = QuestionRepository(session)

    async def create_report(
        self,
        user_id: uuid.UUID,
        question_id: uuid.UUID,
        data: QuestionReportCreateRequest,
    ) -> QuestionReport:
        """Cria um reporte de problema para uma questão."""
        # Verifica se a questão existe
        question = await self._question_repo.get_by_id(question_id)
        if question is None:
            raise NotFoundError("Questão não encontrada.")

        # (Opcional) verifica se o usuário já reportou esta questão.
        # Por simplicidade, permitimos múltiplos reports.

        report = QuestionReport(
            question_id=question_id,
            user_id=user_id,
            reason=data.reason,
            details=data.details,
            status="pendente",
        )
        await self._report_repo.add(report)
        return report