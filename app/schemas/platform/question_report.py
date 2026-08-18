# app/schemas/platform/question_report.py
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import QuestionReportReason


class QuestionReportCreateRequest(BaseModel):
    """Request para criar um reporte de problema."""
    reason: QuestionReportReason
    details: str | None = None


class QuestionReportResponse(BaseModel):
    """Resposta de um reporte de problema."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    user_id: uuid.UUID
    reason: QuestionReportReason
    details: str | None
    status: str
    created_at: datetime