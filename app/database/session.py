# app/database/session.py
"""Engine assíncrono, session factory e dependency de sessão do FastAPI."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# 🔥 CORREÇÃO: `pool_pre_ping=True` removido.
#
# Com o dialeto asyncpg, o mecanismo de pre-ping do SQLAlchemy
# (`do_ping()` -> `self.await_(self._async_ping())`) pode disparar
# `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`
# ao tentar revalidar/reabrir uma conexão logo após um erro de uma
# query anterior na mesma requisição (ex: uma transação que deu
# rollback por uma IntegrityError). Isso é uma limitação conhecida do
# driver assíncrono, não um bug da aplicação — mas o efeito prático é
# transformar um erro de negócio recuperável (que já tinha rollback e
# try/except corretos) num 500 não tratado no meio da resposta.
#
# `pool_recycle` continua garantindo que conexões velhas/obsoletas
# sejam descartadas periodicamente, o que cobre a maior parte do que
# `pool_pre_ping` resolveria, sem o problema do greenlet.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_recycle=1800,  # recicla conexões com mais de 30min
    echo=settings.DEBUG,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency FastAPI: fornece uma sessão por requisição, fecha ao final.

    🔥 CORREÇÃO: agora que os repositórios não engolem mais exceções
    silenciosamente (ver `NotificationRepository`), uma query que falha
    deixa a sessão com uma transação abortada. Sem rollback explícito
    aqui, qualquer código que reutilize a mesma sessão depois de uma
    exceção (o que o handler genérico de `app/core/exceptions.py` não
    faz, mas plugins/middlewares futuros poderiam) receberia o erro
    genérico do driver ("current transaction is aborted") em vez do erro
    original. `session.close()` já dispara rollback implícito na maioria
    dos casos, mas o rollback explícito no `except` deixa o comportamento
    claro e independente de detalhes de driver.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise