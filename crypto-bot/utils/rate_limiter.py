import asyncio
from typing import Dict, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Универсальный rate limiter с поддержкой разных стратегий"""
    
    def __init__(self, rate: int, per: float = 1.0, burst: Optional[int] = None):
        """
        Args:
            rate: Количество разрешенных вызовов
            per: Период в секундах
            burst: Максимальный burst size (если None, то = rate)
        """
        self.rate = rate
        self.per = per
        self.burst = burst or rate
        self.calls = deque(maxlen=self.burst)
        self._lock = asyncio.Lock()
    
    async def acquire(self, n: int = 1) -> float:
        """
        Получение разрешения на n вызовов
        Возвращает время ожидания в секундах
        """
        async with self._lock:
            now = time.time()
            
            # Удаляем старые вызовы
            while self.calls and self.calls[0] <= now - self.per:
                self.calls.popleft()
            
            # Проверяем, можем ли выполнить
            if len(self.calls) + n <= self.rate:
                for _ in range(n):
                    self.calls.append(now)
                return 0.0
            
            # Вычисляем время ожидания
            oldest = self.calls[0]
            wait_time = oldest + self.per - now
            
            # Ждем и добавляем
            await asyncio.sleep(wait_time)
            for _ in range(n):
                self.calls.append(time.time())
            
            return wait_time
    
    async def __aenter__(self):
        """Контекстный менеджер для автоматического rate limiting"""
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class UserRateLimiter:
    """Rate limiter с отдельными лимитами для каждого пользователя"""
    
    def __init__(self, rate: int, per: float = 1.0):
        self.rate = rate
        self.per = per
        self.user_limiters: Dict[int, RateLimiter] = {}
        self._lock = asyncio.Lock()
    
    async def acquire(self, user_id: int, n: int = 1) -> float:
        """Получение разрешения для конкретного пользователя"""
        async with self._lock:
            if user_id not in self.user_limiters:
                self.user_limiters[user_id] = RateLimiter(self.rate, self.per)
        
        return await self.user_limiters[user_id].acquire(n)
    
    def get_stats(self) -> Dict[str, int]:
        """Получение статистики по пользователям"""
        return {
            'total_users': len(self.user_limiters),
            'active_limiters': sum(1 for l in self.user_limiters.values() if len(l.calls) > 0)
        }


class TelegramRateLimiter:
    """Специализированный rate limiter для Telegram API"""
    
    def __init__(self):
        # Глобальный лимит: 30 сообщений в секунду
        self.global_limiter = RateLimiter(30, 1.0, burst=40)
        
        # Лимит по чатам: 20 сообщений в минуту на чат
        self.chat_limiters: Dict[int, RateLimiter] = {}
        
        # Лимит по пользователям: 1 сообщение в секунду
        self.user_limiter = UserRateLimiter(1, 1.0)
        
        self._lock = asyncio.Lock()
        self.stats = defaultdict(int)
    
    async def acquire_for_user(self, user_id: int) -> None:
        """Получение разрешения на отправку сообщения пользователю"""
        # Проверяем все лимиты
        wait_times = await asyncio.gather(
            self.global_limiter.acquire(),
            self.user_limiter.acquire(user_id),
            self._acquire_chat_limit(user_id)
        )
        
        max_wait = max(wait_times)
        if max_wait > 0:
            self.stats['rate_limited'] += 1
            logger.debug(f"Rate limited for user {user_id}, waited {max_wait:.2f}s")
    
    async def _acquire_chat_limit(self, chat_id: int) -> float:
        """Проверка лимита для чата"""
        async with self._lock:
            if chat_id not in self.chat_limiters:
                self.chat_limiters[chat_id] = RateLimiter(20, 60.0)
        
        return await self.chat_limiters[chat_id].acquire()
    
    async def acquire_batch(self, user_ids: list[int]) -> None:
        """Получение разрешения на батч сообщений"""
        # Сортируем по пользователям для минимизации задержек
        for user_id in user_ids:
            await self.acquire_for_user(user_id)
    
    def get_stats(self) -> Dict[str, any]:
        """Получение статистики"""
        return {
            **self.stats,
            'global_queue_size': len(self.global_limiter.calls),
            'chat_limiters': len(self.chat_limiters),
            'user_stats': self.user_limiter.get_stats()
        }


class AdaptiveRateLimiter:
    """Адаптивный rate limiter, который подстраивается под нагрузку"""
    
    def __init__(self, base_rate: int, per: float = 1.0, 
                 min_rate: int = 10, max_rate: int = 100):
        self.base_rate = base_rate
        self.current_rate = base_rate
        self.per = per
        self.min_rate = min_rate
        self.max_rate = max_rate
        
        self.limiter = RateLimiter(self.current_rate, per)
        self.errors = deque(maxlen=100)
        self.successes = deque(maxlen=100)
        
        self._lock = asyncio.Lock()
        self._last_adjustment = time.time()
        self._adjustment_interval = 60.0  # Корректировка раз в минуту
    
    async def acquire(self, n: int = 1) -> float:
        """Получение разрешения с адаптацией"""
        await self._maybe_adjust_rate()
        return await self.limiter.acquire(n)
    
    async def record_result(self, success: bool) -> None:
        """Запись результата для адаптации"""
        async with self._lock:
            if success:
                self.successes.append(time.time())
            else:
                self.errors.append(time.time())
    
    async def _maybe_adjust_rate(self) -> None:
        """Корректировка rate limit на основе статистики"""
        async with self._lock:
            now = time.time()
            if now - self._last_adjustment < self._adjustment_interval:
                return
            
            self._last_adjustment = now
            
            # Считаем процент ошибок за последнюю минуту
            recent_errors = sum(1 for t in self.errors if now - t < 60)
            recent_successes = sum(1 for t in self.successes if now - t < 60)
            total = recent_errors + recent_successes
            
            if total == 0:
                return
            
            error_rate = recent_errors / total
            
            # Адаптируем rate
            if error_rate > 0.1:  # Больше 10% ошибок - снижаем rate
                self.current_rate = max(self.min_rate, int(self.current_rate * 0.8))
                logger.info(f"Decreasing rate limit to {self.current_rate} due to high error rate")
            elif error_rate < 0.01 and recent_successes > 50:  # Меньше 1% ошибок - повышаем
                self.current_rate = min(self.max_rate, int(self.current_rate * 1.2))
                logger.info(f"Increasing rate limit to {self.current_rate} due to low error rate")
            
            # Создаем новый limiter с обновленным rate
            self.limiter = RateLimiter(self.current_rate, self.per)


# Глобальные инстансы для разных сервисов
telegram_limiter = TelegramRateLimiter()
binance_limiter = RateLimiter(1200, 60.0)  # 1200 запросов в минуту
etherscan_limiter = RateLimiter(5, 1.0)  # 5 запросов в секунду