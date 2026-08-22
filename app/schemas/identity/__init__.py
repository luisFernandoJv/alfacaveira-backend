"""Schemas do contexto 'identity'."""

from app.schemas.identity.auth import (
    ForgotPasswordRequest,
    GoogleLoginRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.identity.user import (
    AdminUserListItem,
    AvatarPresignRequest,
    ChangePasswordRequest,
    MeResponse,
    UpdateAccountRequest,
    UpdateProfileRequest,
    UpdateUserStatusRequest,
    UserProfileResponse,
)

__all__ = [
    "AdminUserListItem",
    "AvatarPresignRequest",
    "ChangePasswordRequest",
    "ForgotPasswordRequest",
    "GoogleLoginRequest",
    "LoginRequest",
    "LogoutRequest",
    "MeResponse",
    "RefreshRequest",
    "RegisterRequest",
    "ResetPasswordRequest",
    "TokenResponse",
    "UpdateAccountRequest",
    "UpdateProfileRequest",
    "UpdateUserStatusRequest",
    "UserProfileResponse",
    "UserResponse",
]
