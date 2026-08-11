"""Lock distribuído via Redis para jobs agendados.

Utiliza o padrão Redlock simplificado com SET NX + EXPIRE
para garantir que apenas uma instância execute cada job por vez.

Uso:
    async with DistributedLock(redis_client, "job:analytics", ttl=300) as acquired:
        if acquired:
            # Executa o job
            await run_job()
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class DistributedLock:
    """Lock distribuído via Redis."""

    def __init__(
        self,
        redis_client: redis.Redis,
        lock_key: str,
        ttl: int = 300,
        retry_interval: float = 0.1,
        max_retries: int = 10,
    ):
        """
        Args:
            redis_client: Cliente Redis
            lock_key: Chave única para o lock (ex: "job:analytics")
            ttl: Tempo de vida do lock em segundos
            retry_interval: Intervalo entre tentativas de aquisição
            max_retries: Número máximo de tentativas
        """
        self.redis = redis_client
        self.lock_key = f"lock:{lock_key}"
        self.ttl = ttl
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.lock_value = str(uuid.uuid4())
        self._acquired = False

    async def acquire(self) -> bool:
        """Tenta adquirir o lock."""
        if self.redis is None:
            logger.warning("lock.redis_unavailable", lock_key=self.lock_key)
            return False

        for attempt in range(self.max_retries):
            try:
                # SET key value NX EX ttl
                result = await self.redis.set(
                    self.lock_key,
                    self.lock_value,
                    nx=True,
                    ex=self.ttl,
                )

                if result:
                    self._acquired = True
                    logger.debug(
                        "lock.acquired",
                        lock_key=self.lock_key,
                        lock_value=self.lock_value,
                        attempt=attempt + 1,
                    )
                    return True
            except Exception as e:
                logger.warning(
                    "lock.redis_error",
                    lock_key=self.lock_key,
                    error=str(e),
                    attempt=attempt + 1,
                )

            logger.debug(
                "lock.waiting",
                lock_key=self.lock_key,
                attempt=attempt + 1,
                max_retries=self.max_retries,
            )
            await asyncio.sleep(self.retry_interval)

        logger.warning(
            "lock.acquire_failed",
            lock_key=self.lock_key,
            max_retries=self.max_retries,
        )
        return False

    async def release(self) -> bool:
        """Libera o lock."""
        if not self._acquired or self.redis is None:
            return False

        try:
            # Usa Lua script para garantir atomicidade
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            result = await self.redis.eval(script, 1, self.lock_key, self.lock_value)

            if result:
                self._acquired = False
                logger.debug(
                    "lock.released",
                    lock_key=self.lock_key,
                    lock_value=self.lock_value,
                )
                return True
        except Exception as e:
            logger.warning(
                "lock.release_error",
                lock_key=self.lock_key,
                error=str(e),
            )

        logger.warning(
            "lock.release_failed",
            lock_key=self.lock_key,
            lock_value=self.lock_value,
        )
        return False

    async def refresh(self, ttl: Optional[int] = None) -> bool:
        """Renova o TTL do lock."""
        if not self._acquired or self.redis is None:
            return False

        ttl = ttl or self.ttl
        try:
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("expire", KEYS[1], ARGV[2])
            else
                return 0
            end
            """
            result = await self.redis.eval(script, 1, self.lock_key, self.lock_value, ttl)

            if result:
                logger.debug(
                    "lock.refreshed",
                    lock_key=self.lock_key,
                    ttl=ttl,
                )
                return True
        except Exception as e:
            logger.warning(
                "lock.refresh_error",
                lock_key=self.lock_key,
                error=str(e),
            )

        logger.warning(
            "lock.refresh_failed",
            lock_key=self.lock_key,
            lock_value=self.lock_value,
        )
        return False

    async def __aenter__(self):
        """Entra no contexto (adquire o lock)."""
        self._acquired = await self.acquire()
        return self._acquired

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Sai do contexto (libera o lock)."""
        if self._acquired:
            await self.release()
        return False


def create_lock(
    redis_client: redis.Redis,
    job_name: str,
    ttl: int = 300,
    **kwargs,
) -> DistributedLock:
    """Factory para criar um lock distribuído."""
    return DistributedLock(
        redis_client=redis_client,
        lock_key=f"job:{job_name}",
        ttl=ttl,
        **kwargs,
    )