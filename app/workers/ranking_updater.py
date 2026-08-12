"""Worker de atualização de ranking."""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from app.database.session import AsyncSessionFactory
from app.services.analytics.ranking_service import RankingService

logger = structlog.get_logger(__name__)


async def update_rankings() -> None:
    """
    Atualiza o ranking de todos os usuários.

    Este worker deve ser executado periodicamente (ex: a cada 30 minutos)
    para manter o ranking atualizado.
    """
    logger.info("ranking_updater.starting")
    start_time = datetime.now(UTC)

    try:
        async with AsyncSessionFactory() as session:
            service = RankingService(session)
            await service.update_all_rankings()
            await session.commit()

        duration = (datetime.now(UTC) - start_time).total_seconds()
        logger.info("ranking_updater.completed", duration_seconds=round(duration, 2))

    except Exception as e:
        logger.exception("ranking_updater.failed", error=str(e))
        raise


async def update_single_user(user_id: str) -> None:
    """Atualiza o ranking de um único usuário."""
    try:
        user_uuid = uuid.UUID(user_id)
        async with AsyncSessionFactory() as session:
            service = RankingService(session)
            await service.update_user_ranking(user_uuid)
            await session.commit()
        print(f"✅ Ranking do usuário {user_id} atualizado com sucesso!")
    except ValueError:
        print(f"❌ ID de usuário inválido: {user_id}")
    except Exception as e:
        print(f"❌ Erro ao atualizar usuário {user_id}: {e}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atualiza rankings de usuários"
    )
    parser.add_argument(
        "--user",
        type=str,
        help="ID do usuário para atualizar individualmente (UUID)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.user:
        asyncio.run(update_single_user(args.user))
    else:
        asyncio.run(update_rankings())