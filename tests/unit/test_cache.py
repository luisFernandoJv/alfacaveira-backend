"""Testes unitários para o cache distribuído."""

import pytest
from unittest.mock import AsyncMock

from app.core.cache import Cache


class TestCache:
    """Testes do cache distribuído."""

    @pytest.fixture
    def mock_redis(self):
        """Mock do cliente Redis."""
        redis = AsyncMock()
        redis.get = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.keys = AsyncMock()
        redis.exists = AsyncMock()
        return redis

    @pytest.fixture
    def cache(self, mock_redis):
        """Instância do cache com Redis mockado."""
        return Cache(mock_redis)

    @pytest.mark.asyncio
    async def test_get_returns_value_from_redis(self, cache, mock_redis):
        """Testa que get retorna o valor do Redis."""
        import json
        mock_redis.get.return_value = json.dumps({"test": "value"})
        
        result = await cache.get("test_key")
        
        assert result == {"test": "value"}
        mock_redis.get.assert_called_once_with("cache:test_key")

    @pytest.mark.asyncio
    async def test_get_returns_none_if_not_found(self, cache, mock_redis):
        """Testa que get retorna None se a chave não existir."""
        mock_redis.get.return_value = None
        
        result = await cache.get("test_key")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_set_stores_value_in_redis(self, cache, mock_redis):
        """Testa que set armazena o valor no Redis."""
        import json
        mock_redis.set.return_value = True
        
        result = await cache.set("test_key", {"test": "value"}, ttl=3600)
        
        assert result is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        # CORREÇÃO: verificar argumentos nomeados
        assert call_args.kwargs["name"] == "cache:test_key"
        assert json.loads(call_args.kwargs["value"]) == {"test": "value"}
        assert call_args.kwargs["ex"] == 3600

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, cache, mock_redis):
        """Testa que delete remove a chave do Redis."""
        mock_redis.delete.return_value = 1
        
        result = await cache.delete("test_key")
        
        assert result is True
        mock_redis.delete.assert_called_once_with("cache:test_key")

    @pytest.mark.asyncio
    async def test_clear_pattern_removes_matching_keys(self, cache, mock_redis):
        """Testa que clear_pattern remove chaves que correspondem ao padrão."""
        mock_redis.keys.return_value = ["cache:plans:1", "cache:plans:2"]
        mock_redis.delete.return_value = 2
        
        result = await cache.clear_pattern("plans:*")
        
        assert result == 2
        mock_redis.keys.assert_called_once_with("cache:plans:*")
        mock_redis.delete.assert_called_once_with("cache:plans:1", "cache:plans:2")

    @pytest.mark.asyncio
    async def test_exists_returns_true_if_key_exists(self, cache, mock_redis):
        """Testa que exists retorna True se a chave existe."""
        mock_redis.exists.return_value = 1
        
        result = await cache.exists("test_key")
        
        assert result is True
        mock_redis.exists.assert_called_once_with("cache:test_key")

    @pytest.mark.asyncio
    async def test_get_or_set_returns_cached_value(self, cache, mock_redis):
        """Testa que get_or_set retorna o valor do cache."""
        import json
        mock_redis.get.return_value = json.dumps({"cached": "value"})
        
        async def fetch():
            return {"fetched": "value"}
        
        result = await cache.get_or_set("test_key", fetch)
        
        assert result == {"cached": "value"}
        mock_redis.get.assert_called_once()
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_set_fetches_if_not_cached(self, cache, mock_redis):
        """Testa que get_or_set busca se não estiver em cache."""
        mock_redis.get.return_value = None
        mock_redis.set.return_value = True
        
        async def fetch():
            return {"fetched": "value"}
        
        result = await cache.get_or_set("test_key", fetch, ttl=3600)
        
        assert result == {"fetched": "value"}
        mock_redis.set.assert_called_once()