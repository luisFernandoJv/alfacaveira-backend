"""Schemas de request/response de usuário e perfil."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_exam: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    phone: str | None = None
    birth_date: date | None = None



class AvatarPresignRequest(BaseModel):
    """Solicita uma URL presignada para foto de perfil."""
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(pattern=r"^image/(png|jpeg|webp)$")


class MeResponse(BaseModel):
    """Usuário autenticado com o perfil embutido (usado em GET /users/me)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    profile: UserProfileResponse


class UpdateAccountRequest(BaseModel):
    """Campos de conta (tabela `users`) que o próprio usuário pode alterar."""

    full_name: str | None = Field(default=None, min_length=2, max_length=255)


class UpdateProfileRequest(BaseModel):
    """Campos de perfil (tabela `user_profiles`).

    Todos opcionais: PATCH parcial. Enviar explicitamente `null` limpa o campo.
    """

    target_exam: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=30)
    birth_date: date | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AdminUserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime


class UpdateUserStatusRequest(BaseModel):
    is_active: bool