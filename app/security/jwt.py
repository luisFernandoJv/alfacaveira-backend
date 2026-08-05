"""Emissão e validação de access token (JWT) e refresh token (opaco, hash em DB)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import PyJWTError

from app.core.config import settings

TOKEN_TYPE_ACCESS = "access"


class InvalidTokenError(Exception):
    """Levantada quando um access token é inválido, malformado ou expirado."""


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Cria um access token JWT de vida curta.

    Retorna o token e o tempo de expiração em segundos (para uso em `expires_in`).
    """
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> uuid.UUID:
    """Decodifica e valida um access token, retornando o id do usuário (`sub`).

    Levanta `InvalidTokenError` se o token for inválido, malformado, expirado
    ou não for do tipo `access`.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except PyJWTError as exc:
        raise InvalidTokenError("Token de acesso inválido ou expirado.") from exc

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise InvalidTokenError("Token de acesso inválido.")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Token de acesso inválido.") from exc


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Gera um refresh token opaco.

    Retorna (token em texto puro — devolvido ao cliente uma única vez,
    hash do token — persistido em `refresh_tokens.token_hash`,
    data de expiração).
    """
    plain_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(plain_token)
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return plain_token, token_hash, expires_at


def hash_refresh_token(plain_token: str) -> str:
    """Hash determinístico (SHA-256) do refresh token, para lookup indexado em DB.

    Diferente da senha, o refresh token já é um segredo de alta entropia
    gerado aleatoriamente — não precisa (nem pode, por performance de lookup)
    de um hash lento como Argon2.
    """
    return hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
