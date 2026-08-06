"""Regras de negócio de autenticação: registro, login, refresh (com rotação),
logout e recuperação de senha."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.database.uow import UnitOfWork
from app.models.identity.password_reset_token import PasswordResetToken
from app.models.identity.refresh_token import RefreshToken
from app.models.identity.user import User, UserProfile
from app.repositories.identity.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repositories.identity.refresh_token_repository import RefreshTokenRepository
from app.repositories.identity.user_repository import UserRepository
from app.security.jwt import create_access_token, generate_refresh_token, hash_refresh_token
from app.security.password import hash_password, verify_password
from app.services.identity.email_service import EmailService


@dataclass
class AuthTokens:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    """Orquestra os repositórios de `identity` para os casos de uso de autenticação.

    Services nunca levantam `HTTPException` diretamente (ver `core/exceptions.py`):
    sempre `DomainError` e subclasses, traduzidas para HTTP pelos handlers globais.
    """

    def __init__(self, session: AsyncSession, email_service: EmailService | None = None) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._password_reset_tokens = PasswordResetTokenRepository(session)
        self._email_service = email_service or EmailService()

    async def register(self, email: str, password: str, full_name: str) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise ConflictError("Já existe uma conta cadastrada com este e-mail.")

        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
        )
        async with UnitOfWork(self._session):
            await self._users.add(user)
            profile = UserProfile(user_id=user.id)
            self._session.add(profile)
        return user

    async def login(self, email: str, password: str) -> AuthTokens:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("E-mail ou senha inválidos.")
        if not user.is_active:
            raise UnauthorizedError("Esta conta está desativada.")

        return await self._issue_tokens(user)

    async def refresh(self, plain_refresh_token: str) -> AuthTokens:
        token_hash = hash_refresh_token(plain_refresh_token)
        stored_token = await self._refresh_tokens.get_by_hash(token_hash)

        if stored_token is None or stored_token.revoked_at is not None:
            raise UnauthorizedError("Refresh token inválido ou revogado.")

        if stored_token.expires_at < datetime.now(UTC):
            raise UnauthorizedError("Refresh token expirado.")

        user = await self._users.get_by_id(stored_token.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Usuário inválido ou inativo.")

        async with UnitOfWork(self._session):
            new_plain_token, new_token_hash, new_expires_at = generate_refresh_token()
            new_token = RefreshToken(
                user_id=user.id,
                token_hash=new_token_hash,
                expires_at=new_expires_at,
            )
            await self._refresh_tokens.add(new_token)
            await self._refresh_tokens.revoke(stored_token, replaced_by_token_id=new_token.id)

        access_token, expires_in = create_access_token(user.id)
        return AuthTokens(
            user=user,
            access_token=access_token,
            refresh_token=new_plain_token,
            expires_in=expires_in,
        )

    async def logout(self, plain_refresh_token: str) -> None:
        token_hash = hash_refresh_token(plain_refresh_token)
        stored_token = await self._refresh_tokens.get_by_hash(token_hash)
        if stored_token is None or stored_token.revoked_at is not None:
            return
        async with UnitOfWork(self._session):
            await self._refresh_tokens.revoke(stored_token)

    async def forgot_password(self, email: str) -> None:
        """Inicia a recuperação de senha.

        Por design, não revela se o e-mail existe ou não na base: o método
        sempre "funciona" do ponto de vista do chamador (endpoint sempre
        responde 204). Se o e-mail pertencer a um usuário ativo, um link de
        redefinição é enviado; caso contrário, a chamada é um no-op. Isso
        evita que o endpoint seja usado para enumerar contas cadastradas.
        """
        user = await self._users.get_by_email(email)
        if user is None or not user.is_active:
            return

        async with UnitOfWork(self._session):
            # Invalida qualquer link de recuperação anterior ainda válido,
            # para que só o mais recente funcione.
            await self._password_reset_tokens.invalidate_all_for_user(user.id)

            plain_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
            expires_at = datetime.now(UTC) + timedelta(
                minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
            )
            reset_token = PasswordResetToken(
                user_id=user.id, token_hash=token_hash, expires_at=expires_at
            )
            await self._password_reset_tokens.add(reset_token)

        reset_url = f"{settings.FRONTEND_URL}/redefinir-senha?token={plain_token}"
        await self._email_service.send_password_reset_email(
            to_email=user.email, to_name=user.full_name, reset_url=reset_url
        )

    async def reset_password(self, plain_token: str, new_password: str) -> None:
        token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
        stored_token = await self._password_reset_tokens.get_valid_by_hash(token_hash)
        if stored_token is None:
            raise UnauthorizedError("Link de redefinição inválido ou expirado.")

        user = await self._users.get_by_id(stored_token.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Link de redefinição inválido ou expirado.")

        async with UnitOfWork(self._session):
            user.password_hash = hash_password(new_password)
            await self._password_reset_tokens.mark_used(stored_token)
            # Redefinir a senha revoga todas as sessões ativas (refresh tokens):
            # se a conta foi comprometida, isso derruba qualquer acesso indevido
            # em outros dispositivos assim que a senha é trocada.
            for refresh_token in await self._refresh_tokens.list_active_for_user(user.id):
                await self._refresh_tokens.revoke(refresh_token)

    async def _issue_tokens(self, user: User) -> AuthTokens:
        access_token, expires_in = create_access_token(user.id)
        plain_refresh_token, token_hash, expires_at = generate_refresh_token()
        refresh_token_row = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        async with UnitOfWork(self._session):
            await self._refresh_tokens.add(refresh_token_row)

        return AuthTokens(
            user=user,
            access_token=access_token,
            refresh_token=plain_refresh_token,
            expires_in=expires_in,
        )