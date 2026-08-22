"""Endpoints HTTP de autenticação: registro, login local, Google, refresh,
logout, recuperação e redefinição de senha."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import Envelope
from app.database.session import get_db
from app.schemas.identity import (
    ForgotPasswordRequest,
    GoogleLoginRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.identity import AuthService

router = APIRouter()


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    response_model=Envelope[TokenResponse],
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, auth_service: AuthServiceDep) -> Envelope[TokenResponse]:
    """Cria a conta local e já inicia a sessão."""
    tokens = await auth_service.register(
        email=body.email, password=body.password, full_name=body.full_name
    )
    return Envelope(
        data=TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )


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


@router.post("/google", response_model=Envelope[TokenResponse])
async def login_with_google(
    body: GoogleLoginRequest, auth_service: AuthServiceDep
) -> Envelope[TokenResponse]:
    """Valida a credencial do Google e inicia a sessão local da plataforma."""
    tokens = await auth_service.login_with_google(body.credential)
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


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(body: ForgotPasswordRequest, auth_service: AuthServiceDep) -> None:
    """Sempre responde 204, exista ou não uma conta com o e-mail informado."""
    await auth_service.forgot_password(body.email)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetPasswordRequest, auth_service: AuthServiceDep) -> None:
    await auth_service.reset_password(body.token, body.new_password)
