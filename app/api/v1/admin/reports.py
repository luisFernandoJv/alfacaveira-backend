import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.responses import Envelope
from app.database.session import get_db
from app.models.platform.question_report import QuestionReport
from app.security.dependencies import CurrentAdminUser

router = APIRouter()


class AdminQuestionReportItem(BaseModel):
    """Item de report no formato esperado por
    app/(app)/admin/question-reports/page.tsx (campos achatados,
    `user_name` / `question_statement` em vez de objetos aninhados)."""

    id: uuid.UUID
    question_id: uuid.UUID
    user_id: uuid.UUID
    reason: str
    details: str | None
    status: str
    created_at: str
    user_name: str | None = None
    question_statement: str | None = None


class ModerateReportRequest(BaseModel):
    action: Literal["approve", "reject"]


@router.get("/question-reports", response_model=Envelope[list[AdminQuestionReportItem]])
async def list_question_reports(
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> Envelope[list[AdminQuestionReportItem]]:
    stmt = (
        select(QuestionReport)
        .options(
            selectinload(QuestionReport.question),
            selectinload(QuestionReport.user),
        )
        .order_by(QuestionReport.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(QuestionReport.status == status_filter)

    result = await session.execute(stmt)
    reports = list(result.scalars().unique().all())

    items = [
        AdminQuestionReportItem(
            id=r.id,
            question_id=r.question_id,
            user_id=r.user_id,
            reason=r.reason.value if hasattr(r.reason, "value") else r.reason,
            details=r.details,
            status=r.status,
            created_at=r.created_at.isoformat(),
            user_name=r.user.full_name if r.user else None,
            question_statement=r.question.statement if r.question else None,
        )
        for r in reports
    ]
    return Envelope(data=items)


@router.post("/question-reports/{report_id}/moderate", response_model=Envelope[AdminQuestionReportItem])
async def moderate_question_report(
    report_id: uuid.UUID,
    body: ModerateReportRequest,
    admin: CurrentAdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[AdminQuestionReportItem]:
    stmt = (
        select(QuestionReport)
        .options(
            selectinload(QuestionReport.question),
            selectinload(QuestionReport.user),
        )
        .where(QuestionReport.id == report_id)
    )
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report não encontrado.")

    report.status = "aprovado" if body.action == "approve" else "rejeitado"
    await session.commit()
    await session.refresh(report, attribute_names=["question", "user"])

    return Envelope(
        data=AdminQuestionReportItem(
            id=report.id,
            question_id=report.question_id,
            user_id=report.user_id,
            reason=report.reason.value if hasattr(report.reason, "value") else report.reason,
            details=report.details,
            status=report.status,
            created_at=report.created_at.isoformat(),
            user_name=report.user.full_name if report.user else None,
            question_statement=report.question.statement if report.question else None,
        )
    )