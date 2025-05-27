"""Rate limiting utilities."""

import asyncio
import time
from collections import deque
from typing import Dict, Optional
from config.settings import Config
import structlog

logger = structlog.get_logger()


class RateLimiter:
    """Generic rate limiter."""
    
    def __init__(self, max_calls: int, period: int):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum number of calls allowed
            period: Time period in seconds
        """
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Acquire permission to make a call."""
        async with self.lock:
            now = time.time()
            
            # Remove old calls outside the period
            while self.calls and now - self.calls[0] >= self.period:
                self.calls.popleft()
            
            # If we're at the limit, wait
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    return await self.acquire()  # Try again
            
            # Record this call
            self.calls.append(now)
    
    def can_proceed(self) -> bool:
        """Check if we can proceed without waiting."""
        now = time.time()
        
        # Remove old calls
        while self.calls and now - self.calls[0] >= self.period:
            self.calls.popleft()
        
        return len(self.calls) < self.max_calls


class TelegramRateLimiter:
    """Specialized rate limiter for Telegram API."""
    
    def __init__(self):
        self.global_limiter = RateLimiter(Config.TELEGRAM_RATE_LIMIT, 1)  # 30/sec
        self.chat_limiters: Dict[int, RateLimiter] = {}
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    async def acquire_for_chat(self, chat_id: int) -> None:
        """Acquire rate limit for specific chat."""
        # Global rate limit
        await self.global_limiter.acquire()
        
        # Per-chat rate limit (1 message per second per chat)
        if chat_id not in self.chat_limiters:
            self.chat_limiters[chat_id] = RateLimiter(1, 1)
        
        await self.chat_limiters[chat_id].acquire()
        
        # Cleanup old limiters periodically
        await self._cleanup_old_limiters()
    
    async def _cleanup_old_limiters(self) -> None:
        """Remove unused chat limiters to save memory."""
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        
        # Remove limiters with no recent activity
        inactive_chats = []
        for chat_id, limiter in self.chat_limiters.items():
            if not limiter.calls or now - limiter.calls[-1] > self.cleanup_interval:
                inactive_chats.append(chat_id)
        
        for chat_id in inactive_chats:
            del self.chat_limiters[chat_id]
        
        self.last_cleanup = now
        
        if inactive_chats:
            logger.debug(f"Cleaned up {len(inactive_chats)} inactive chat limiters")


class BinanceRateLimiter:
    """Rate limiter for Binance API calls."""
    
    def __init__(self):
        # Binance limits: 1200 requests per minute for API
        self.api_limiter = RateLimiter(1200, 60)
        
        # WebSocket connection limits
        self.ws_connection_limiter = RateLimiter(5, 1)  # 5 connections per second
    
    async def acquire_api(self) -> None:
        """Acquire rate limit for API call."""
        await self.api_limiter.acquire()
    
    async def acquire_ws_connection(self) -> None:
        """Acquire rate limit for WebSocket connection."""
        await self.ws_connection_limiter.acquire()


# Global rate limiter instances
telegram_limiter = TelegramRateLimiter()
binance_limiter = BinanceRateLimiter()