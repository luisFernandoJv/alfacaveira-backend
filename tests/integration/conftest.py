"""Fixtures globais do Pytest (event loop, sessão de banco de teste, client).

Etapa 13 + roadmap item 7 (fechamento): fixture de Postgres efêmero real,
substituindo o placeholder anterior. Ver ADR-020 (docs/DECISIONS.md) para o
raciocínio da escolha testcontainers-python vs. docker-compose.

VALIDADO CONTRA EXECUÇÃO REAL (rodado por você, não nesta sessão de escrita
— ver docs/HANDOFF.md): a primeira versão deste arquivo tinha dois bugs
reais, encontrados só ao rodar de fato:

1. `migrations/env.py` (código real do projeto) faz
   `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)` —
   sobrescreve qualquer URL passada programaticamente ao `Config` do
   Alembic. A primeira versão desta fixture configurava a URL do
   container via `AlembicConfig.set_main_option`, que era simplesmente
   ignorada — `alembic upgrade head` rodava contra `settings.DATABASE_URL`
   (o Postgres do `.env` local, sem as tabelas do teste), não contra o
   container efêmero. Resultado: `relation "plans" does not exist`.
   Correção: em vez de brigar com o `env.py`, rodar `alembic upgrade head`
   num subprocesso com a variável de ambiente `DATABASE_URL` apontando
   para o container — como `Settings` (pydantic-settings) lê de variável
   de ambiente, e o subprocesso é um processo Python novo (sem cache de
   import), `settings.DATABASE_URL` dentro do `env.py` acaba correto sem
   precisar tocar no `env.py` do projeto.
2. `db_engine` era `session-scoped`, mas o `pytest-asyncio` cria um event
   loop novo por função de teste por padrão — o engine e seu pool de
   conexões ficavam presos ao loop do primeiro teste; no segundo teste,
   com um loop novo, dava `RuntimeError: ... attached to a different
   loop` / `Event loop is closed`. Correção: `db_engine` agora é
   function-scoped (engine novo, descartado ao final de cada teste) — só
   o container Docker em si (que não é asyncio) continua session-scoped.

Estratégia (inalterada em relação à v1):
- Um container Postgres por sessão de teste (`postgres_container`,
  session-scoped) — sobe uma vez.
- Schema aplicado via Alembic real (`alembic upgrade head`, agora via
  subprocesso — ver ponto 1 acima), não via `Base.metadata.create_all`.
- Isolamento por teste via savepoint/rollback (`db_session`,
  function-scoped) para testes que não são de concorrência.
- `db_engine` (agora function-scoped, ver ponto 2 acima): para os testes
  de concorrência real, que precisam de sessões independentes e
  *committadas* de verdade disputando a mesma linha.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# testcontainers-python (ver ADR-020): sobe um Postgres real efêmero via
# Docker, sem exigir docker-compose nem serviço dedicado em CI.
# `testcontainers.postgres` está deprecado a favor de
# `testcontainers.community.postgres` (aviso visto na execução real) —
# tenta o caminho novo primeiro, cai para o antigo em versões mais velhas
# da lib.
try:
    from testcontainers.community.postgres import PostgresContainer
except ImportError:  # pragma: no cover - versão mais antiga de testcontainers
    from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container() -> AsyncIterator[PostgresContainer]:
    """Sobe um Postgres 16 efêmero (mesma major version usada em produção
    via Supabase, ver docs/PROJECT_STATE.md §2) uma vez por sessão de teste.
    """
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(postgres_container: PostgresContainer) -> None:
    """Aplica todas as migrations reais (não `create_all`) contra o
    container, uma única vez por sessão de teste.

    Roda `alembic upgrade head` num SUBPROCESSO, não via
    `alembic.command.upgrade()` in-process — ver ponto 1 da docstring do
    módulo para o porquê (o `env.py` real do projeto sobrescreve
    `sqlalchemy.url` com `settings.DATABASE_URL`; setar a variável de
    ambiente antes de um processo novo é o jeito confiável de fazer o
    `env.py` original enxergar a URL certa sem editá-lo).
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_container.get_connection_url()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head falhou contra o Postgres efêmero de teste:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


@pytest_asyncio.fixture
async def db_engine(postgres_container: PostgresContainer) -> AsyncGenerator[AsyncEngine, None]:
    """Engine assíncrono bruto, para os testes de concorrência real que
    precisam de commits de verdade em sessões independentes.

    FUNCTION-scoped (não session-scoped) de propósito: o `pytest-asyncio`
    dá um event loop novo por função de teste por padrão, e um engine
    asyncpg preso a um loop já fechado quebra com "attached to a
    different loop"/"Event loop is closed" no teste seguinte (visto na
    execução real). Criar e descartar (`dispose`) um engine por teste
    custa pouco perto do resto do teste (semear dados, rodar duas
    chamadas concorrentes) e evita o problema de raiz. O container Docker
    em si continua session-scoped — só o engine Python é recriado.
    """
    engine = create_async_engine(postgres_container.get_connection_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Sessão isolada por teste via savepoint: abre uma conexão + transação
    externa, uma `AsyncSession` "presa" a ela (`join_transaction_mode=
    "create_savepoint"`), e desfaz tudo ao final — nenhum teste que usar
    esta fixture enxerga o efeito de outro, nem precisa limpar depois de si.

    NÃO usar esta fixture nos testes de `tests/integration/` que simulam
    concorrência real entre duas transações committadas — para esses, usar
    `db_engine` diretamente e abrir as sessões manualmente (ver
    `tests/integration/test_subscription_concurrency_postgres.py`).
    """
    connection = await db_engine.connect()
    outer_transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    async with session_factory() as session:
        yield session
    await outer_transaction.rollback()
    await connection.close()