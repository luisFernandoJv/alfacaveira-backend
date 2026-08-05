"""Endpoints HTTP de autenticação: registro, login, refresh, logout, /me."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.identity import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.identity import AuthService

router = APIRouter()


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    response_model=Envelope[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, auth_service: AuthServiceDep) -> Envelope[UserResponse]:
    user = await auth_service.register(
        email=body.email, password=body.password, full_name=body.full_name
    )
    return Envelope(data=UserResponse.model_validate(user))


@router.post("/login", response_model=Envelope[TokenResponse])
async def login(body: LoginRequest, auth_service: AuthServiceDep) -> Envelope[TokenResponse]:
    tokens = await auth_service.login(email=body.email, password=body.password)
    return Envelope(
        data=TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )


@router.post("/refresh", response_model=Envelope[TokenResponse])
async def refresh(body: RefreshRequest, auth_service: AuthServiceDep) -> Envelope[TokenResponse]:
    tokens = await auth_service.refresh(body.refresh_token)
    return Envelope(
        data=TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, auth_service: AuthServiceDep) -> None:
    await auth_service.logout(body.refresh_token)
