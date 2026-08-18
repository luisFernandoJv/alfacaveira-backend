"""Router agregador da API v1."""

from fastapi import APIRouter
from app.api.v1.content.exam_papers import router as exam_papers_router
from app.api.v1.assessment.exam_attempts import router as exam_attempts_router
from app.api.v1.assessment.exam_templates import router as exam_templates_router
from app.api.v1.billing.plans import router as billing_plans_router
from app.api.v1.billing.subscriptions import router as billing_subscriptions_router
from app.api.v1.billing.webhooks import router as billing_webhooks_router
from app.api.v1.content.exam_sources import router as exam_sources_router
from app.api.v1.content.questions import router as questions_router
from app.api.v1.content.question_states import router as question_states_router
from app.api.v1.content.question_stats import router as question_stats_router
from app.api.v1.content.taxonomy import router as taxonomy_router
from app.api.v1.identity.auth import router as auth_router
from app.api.v1.identity.users import router as users_router
from app.api.v1.practice.attempts import router as attempts_router
from app.api.v1.practice.training_sessions import router as training_sessions_router
from app.api.v1.practice.reviews import router as reviews_router
from app.api.v1.analytics.ranking import router as ranking_router
from app.api.v1.platform.comments import router as comments_router
from app.api.v1.platform.notifications import router as notifications_router
from app.api.v1.analytics.user_stats import router as user_stats_router
from app.api.v1.learning.notebooks import router as notebooks_router
from app.api.v1.learning.flashcards import router as flashcards_router
from app.api.v1.admin import router as admin_router

api_router = APIRouter()

# Auth
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])

# Users
api_router.include_router(users_router, prefix="/users", tags=["users"])

# ⚠️ IMPORTANTE: question_stats_router DEVE vir ANTES de questions_router
# para que /questions/stats não seja capturado como um question_id
api_router.include_router(
    question_stats_router,
    prefix="/questions",
    tags=["questions"],
)

api_router.include_router(
    question_states_router,
    prefix="/questions",
    tags=["questions"],
)

api_router.include_router(questions_router, prefix="/questions", tags=["questions"])
api_router.include_router(taxonomy_router, tags=["taxonomy"])
api_router.include_router(exam_sources_router, tags=["exam-sources"])

# Practice
api_router.include_router(
    training_sessions_router, prefix="/training-sessions", tags=["training-sessions"]
)
api_router.include_router(attempts_router, prefix="/attempts", tags=["attempts"])

# Assessment
api_router.include_router(
    exam_templates_router, prefix="/exam-templates", tags=["exam-templates"]
)
api_router.include_router(
    exam_attempts_router, prefix="/exam-attempts", tags=["exam-attempts"]
)

# Billing
api_router.include_router(billing_plans_router, prefix="/billing/plans", tags=["billing"])
api_router.include_router(
    billing_subscriptions_router, prefix="/billing/subscriptions", tags=["billing"]
)
api_router.include_router(
    billing_webhooks_router, prefix="/billing/webhooks", tags=["billing"]
)

# Reviews
api_router.include_router(
    reviews_router,
    prefix="/reviews",
    tags=["reviews"],
)

# Exam Papers
api_router.include_router(
    exam_papers_router,
    prefix="/exam-papers",
    tags=["exam-papers"],
)

# Ranking
api_router.include_router(
    ranking_router,
    prefix="/ranking",
    tags=["ranking"],
)

# Platform - Comments
api_router.include_router(
    comments_router,
    prefix="/comments",
    tags=["comments"],
)

# Platform - Notifications
api_router.include_router(
    notifications_router,
    prefix="/notifications",
    tags=["notifications"],
)

# Analytics
api_router.include_router(
    user_stats_router,
    prefix="/analytics",
    tags=["analytics"],
)

# Learning - Notebooks
api_router.include_router(
    notebooks_router,
    prefix="/notebooks",
    tags=["notebooks"],
)

# Learning - Flashcards
api_router.include_router(
    flashcards_router,
    prefix="/flashcards",
    tags=["flashcards"],
)

api_router.include_router(admin_router, prefix="/admin", tags=["admin"])