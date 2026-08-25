from fastapi import APIRouter

from app.api.v1.admin.reports import router as reports_router
from app.api.v1.admin.stats import router as stats_router
from app.api.v1.admin.users import router as users_router
from app.api.v1.admin.notifications import router as notifications_router

router = APIRouter()
router.include_router(reports_router)
router.include_router(stats_router)
router.include_router(users_router)