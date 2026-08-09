"""Router agregador da API v1.

Reúne os routers de cada bounded context conforme cada módulo é
implementado (Etapas 5 em diante: Autenticação, Usuários, Questões, ...).
"""

from fastapi import APIRouter

from app.api.v1.assessment.exam_attempts import router as exam_attempts_router
from app.api.v1.assessment.exam_templates import router as exam_templates_router
from app.api.v1.billing.plans import router as billing_plans_router
from app.api.v1.billing.subscriptions import router as billing_subscriptions_router
from app.api.v1.billing.webhooks import router as billing_webhooks_router
from app.api.v1.content.exam_sources import router as exam_sources_router
from app.api.v1.content.questions import router as questions_router
from app.api.v1.content.taxonomy import router as taxonomy_router
from app.api.v1.identity.auth import router as auth_router
from app.api.v1.identity.users import router as users_router
from app.api.v1.practice.attempts import router as attempts_router
from app.api.v1.practice.training_sessions import router as training_sessions_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(questions_router, prefix="/questions", tags=["questions"])
api_router.include_router(taxonomy_router, tags=["taxonomy"])
api_router.include_router(exam_sources_router, tags=["exam-sources"])
api_router.include_router(
    training_sessions_router, prefix="/training-sessions", tags=["training-sessions"]
)
api_router.include_router(attempts_router, prefix="/attempts", tags=["attempts"])
api_router.include_router(
    exam_templates_router, prefix="/exam-templates", tags=["exam-templates"]
)
api_router.include_router(
    exam_attempts_router, prefix="/exam-attempts", tags=["exam-attempts"]
)
api_router.include_router(billing_plans_router, prefix="/billing/plans", tags=["billing"])
api_router.include_router(
    billing_subscriptions_router, prefix="/billing/subscriptions", tags=["billing"]
)
api_router.include_router(
    billing_webhooks_router, prefix="/billing/webhooks", tags=["billing"]
)

# Etapa 10+: api_router.include_router(...)