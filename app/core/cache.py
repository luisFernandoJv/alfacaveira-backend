"""Cache distribuído via Redis para dados estáticos e sessão."""

import json
from typing import Any, Optional
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class Cache:
    """Cache distribuído via Redis."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._prefix = "cache:"

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Optional[Any]:
        if self.redis is None:
            return None

        try:
            value = await self.redis.get(self._key(key))
            if value is None:
                return None
            # Tenta parsear como JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Se não for JSON, retorna o valor como string
                return value
        except Exception as e:
            logger.warning("cache.get_error", key=key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = 3600,
    ) -> bool:
        if self.redis is None:
            return False

        try:
            # Serializa para JSON com fallback para str
            try:
                serialized = json.dumps(value, default=str)
            except (TypeError, ValueError):
                serialized = str(value)
            
            await self.redis.set(
                name=self._key(key),
                value=serialized,
                ex=ttl,
            )
            logger.debug("cache.set", key=key, ttl=ttl)
            return True
        except Exception as e:
            logger.warning("cache.set_error", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        if self.redis is None:
            return False

        try:
            await self.redis.delete(self._key(key))
            logger.debug("cache.delete", key=key)
            return True
        except Exception as e:
            logger.warning("cache.delete_error", key=key, error=str(e))
            return False

    async def clear_pattern(self, pattern: str) -> int:
        if self.redis is None:
            return 0

        try:
            keys = await self.redis.keys(f"{self._prefix}{pattern}")
            if keys:
                return await self.redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning("cache.clear_pattern_error", pattern=pattern, error=str(e))
            return 0

    async def exists(self, key: str) -> bool:
        if self.redis is None:
            return False

        try:
            return await self.redis.exists(self._key(key)) > 0
        except Exception:
            return False

    async def get_or_set(
        self,
        key: str,
        fetch_func,
        ttl: int = 3600,
        *args,
        **kwargs,
    ) -> Optional[Any]:
        cached = await self.get(key)
        if cached is not None:
            logger.debug("cache.hit", key=key)
            return cached

        logger.debug("cache.miss", key=key)
        value = await fetch_func(*args, **kwargs)
        
        if value is not None:
            await self.set(key, value, ttl=ttl)
        
        return value


def get_cache() -> Optional[Cache]:
    try:
        from app.main import app
        redis_client = getattr(app.state, "redis", None)
        if redis_client is None:
            return None
        return Cache(redis_client)
    except Exception:
        return None