"""Unit of Work: agrupa operações multi-repositório em uma transação atômica.

Uso típico dentro de um service:

    async with UnitOfWork(session) as uow:
        await repo_a.create(..., session=uow.session)
        await repo_b.update(..., session=uow.session)
        # commit automático ao sair do bloco sem exceção; rollback se houver erro.
"""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> "UnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
