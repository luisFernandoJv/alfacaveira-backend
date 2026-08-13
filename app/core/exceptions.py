# app/core/exceptions.py
"""Exceções de domínio e seus handlers HTTP.

Services levantam estas exceções (nunca HTTPException diretamente — isso
acopla a camada de negócio ao FastAPI). Os handlers registrados em `main.py`
traduzem cada uma para o envelope de resposta padrão + status code correto.

🔥 CORREÇÃO: Adicionado handler genérico para `Exception`. Antes, qualquer
exceção que não fosse `DomainError` (AttributeError, IntegrityError, erro de
SQLAlchemy, MissingGreenlet, etc.) não tinha handler registrado e caía no
tratamento padrão do Starlette. Combinado com múltiplos `BaseHTTPMiddleware`
empilhados (RateLimitMiddleware + ObservabilityMiddleware), isso resultava
em respostas truncadas/vazias para o cliente (o sintoma do
`JSONDecodeError: Expecting value: line 1 column 3 (char 2)`), e o
traceback real nunca aparecia em lugar nenhum.

Agora:
- Qualquer exceção não mapeada gera um JSON válido (envelope de erro padrão)
  em vez de uma resposta vazia/corrompida.
- O traceback completo é logado via structlog, o que finalmente expõe a
  causa raiz real no `docker compose logs api`.
"""

import traceback

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.responses import error_envelope

logger = structlog.get_logger(__name__)


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

    # 🔥 CORREÇÃO: handler para RequestValidationError (erros de validação
    # do Pydantic no corpo/query/path da request). Sem isso, o FastAPI usa
    # seu handler embutido, que devolve {"detail": [...]}  — um formato
    # diferente do envelope {data, meta, error} usado no resto da API.
    # O frontend (`lib/api.ts`) só lê `body.error.message`, então todo 422
    # virava a mensagem genérica "Erro 422 ao chamar {path}", escondendo
    # qual campo falhou e por quê.
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else None
        if first is not None:
            # loc costuma ser algo como ("body", "name") ou ("query", "limit")
            field = ".".join(str(part) for part in first["loc"][1:]) or str(
                first["loc"][-1]
            )
            message = f"{field}: {first['msg']}" if field else first["msg"]
        else:
            message = "Dados inválidos na requisição."

        logger.warning(
            "validation_error",
            path=request.url.path,
            method=request.method,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_envelope(code="validation_error", message=message),
        )

    # 🔥 CORREÇÃO CRÍTICA: handler genérico. Sem isso, qualquer exceção
    # inesperada resultava em resposta vazia/corrompida para o cliente.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_envelope(
                code="internal_error",
                message="Erro interno do servidor.",
            ),
        )