"""Testes unitários para o lock distribuído."""

import pytest
from unittest.mock import AsyncMock

from app.core.lock import DistributedLock, create_lock


class TestDistributedLock:
    """Testes do lock distribuído."""

    @pytest.fixture
    def mock_redis(self):
        """Mock do cliente Redis."""
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.eval = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_acquire_returns_true_if_lock_acquired(self, mock_redis):
        """Testa que acquire retorna True se o lock for adquirido."""
        mock_redis.set.return_value = True
        lock = DistributedLock(mock_redis, "test_lock", ttl=300)
        
        result = await lock.acquire()
        
        assert result is True
        assert lock._acquired is True
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_returns_false_if_lock_busy(self, mock_redis):
        """Testa que acquire retorna False se o lock estiver ocupado."""
        mock_redis.set.return_value = None
        lock = DistributedLock(mock_redis, "test_lock", ttl=300, max_retries=2)
        
        result = await lock.acquire()
        
        assert result is False
        assert lock._acquired is False
        assert mock_redis.set.call_count == 2

    @pytest.mark.asyncio
    async def test_release_returns_true_if_lock_released(self, mock_redis):
        """Testa que release retorna True se o lock for liberado."""
        mock_redis.eval.return_value = 1
        lock = DistributedLock(mock_redis, "test_lock", ttl=300)
        lock._acquired = True
        
        result = await lock.release()
        
        assert result is True
        assert lock._acquired is False
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_returns_false_if_lock_not_acquired(self, mock_redis):
        """Testa que release retorna False se o lock não foi adquirido."""
        lock = DistributedLock(mock_redis, "test_lock", ttl=300)
        lock._acquired = False
        
        result = await lock.release()
        
        assert result is False
        mock_redis.eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager_acquires_and_releases(self, mock_redis):
        """Testa que o context manager adquire e libera o lock."""
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1
        lock = DistributedLock(mock_redis, "test_lock", ttl=300)
        
        # CORREÇÃO: o context manager retorna o lock, não o acquired
        async with lock as acquired:
            assert acquired is True
            assert lock._acquired is True
        
        assert lock._acquired is False
        mock_redis.set.assert_called_once()
        mock_redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_lock_factory(self, mock_redis):
        """Testa a factory create_lock."""
        lock = create_lock(mock_redis, "test_job", ttl=600)
        
        assert lock.lock_key == "lock:job:test_job"
        assert lock.ttl == 600
        assert lock.retry_interval == 0.1
        assert lock.max_retries == 10