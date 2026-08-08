"""Dependencies FastAPI para autenticação/autorização (get_current_user etc.)
e para os Feature Gates de Billing (`RequireFeature`).
"""

from typing import Annotated, Callable, Coroutine

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.database.session import get_db
from app.models.enums import FeatureKey
from app.models.identity.user import User
from app.repositories.identity.user_repository import UserRepository
from app.security.jwt import InvalidTokenError, decode_access_token
from app.services.billing.feature_gate_service import FeatureGateService

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve o usuário autenticado a partir do access token no header `Authorization`."""
    if credentials is None:
        raise UnauthorizedError("Não autenticado.")

    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Usuário inválido ou inativo.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin_user(user: CurrentUser) -> User:
    """Igual a `get_current_user`, mas exige que o usuário seja administrador."""
    if not user.is_admin:
        raise ForbiddenError("Acesso restrito a administradores.")
    return user


CurrentAdminUser = Annotated[User, Depends(get_current_admin_user)]


def RequireFeature(key: FeatureKey) -> Callable[..., Coroutine[None, None, None]]:
    """Dependency factory de Feature Gate para uso em rotas de módulos
    consumidores (`practice`, `assessment`, `analytics`, `learning`, ...).

    Uso: `dependencies=[Depends(RequireFeature(FeatureKey.SIMULADOS))]` no
    decorator da rota. O endpoint nunca precisa conhecer `Plan`,
    `Subscription` ou `PlanFeature` — só o `FeatureKey` sendo exigido.
    Levanta `ForbiddenError` (via `FeatureGateService.assert_feature`) se o
    plano efetivo do usuário autenticado não incluir a feature.
    """

    async def _require_feature(
        user: CurrentUser,
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        await FeatureGateService(session).assert_feature(user.id, key)

    return _require_feature