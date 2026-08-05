"""Exceções de domínio e seus handlers HTTP.

Services levantam estas exceções (nunca HTTPException diretamente — isso
acopla a camada de negócio ao FastAPI). Os handlers registrados em `main.py`
traduzem cada uma para o envelope de resposta padrão + status code correto.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.responses import error_envelope


class DomainError(Exception):
    """Exceção base de regra de negócio."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ValidationDomainError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code=exc.code, message=exc.message),
        )
