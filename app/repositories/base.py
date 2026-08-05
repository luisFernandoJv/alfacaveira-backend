"""Interface genérica de repositório (Protocol) + implementação base async."""

import uuid
from typing import Generic, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class Repository(Protocol[ModelType]):
    """Contrato mínimo que todo repositório concreto deve cumprir.

    Definido como Protocol (duck typing estrutural) para permitir repositórios
    fake em testes de `services/`, sem depender de herança nem de banco real.
    """

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelType | None: ...

    async def add(self, entity: ModelType) -> ModelType: ...


class BaseRepository(Generic[ModelType]):
    """Implementação base assíncrona sobre SQLAlchemy, reutilizada pelos
    repositórios concretos de cada bounded context via `model = MeuModel`.
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelType | None:
        return await self.session.get(self.model, entity_id)

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        return entity
