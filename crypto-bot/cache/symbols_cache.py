import logging
from typing import List
from datetime import datetime
import asyncio

from services.binanceAPI.service import binance_api

logger = logging.getLogger(__name__)


class SymbolsCache:
    """Кеш символов в памяти - работает только с памятью после инициализации"""
    
    def __init__(self):
        self.symbols: List[str] = []
        self.loaded_at: datetime = None
        self._lock = asyncio.Lock()
        self._initialized = False
        
    async def initialize(self):
        """Одноразовая загрузка символов при старте"""
        if self._initialized:
            return
            
        async with self._lock:
            if self._initialized:  # Double check
                return
                
            logger.info("Initializing symbols cache...")
            
            # Загружаем символы из API
            symbols = await binance_api.fetch_all_futures_symbols()
            
            if not symbols:
                logger.error("Failed to load symbols from API")
                return
            
            self.symbols = symbols
            self.loaded_at = datetime.now()
            self._initialized = True
            
            logger.info(f"Symbols cache initialized with {len(self.symbols)} symbols")
    
    def get_all_symbols(self) -> List[str]:
        """Получение всех символов из памяти"""
        if not self._initialized:
            logger.warning("Symbols cache not initialized, returning empty list")
            return []
        return self.symbols.copy()
    
    def get_top_symbols(self, limit: int = 100) -> List[str]:
        """Получение топ символов из памяти"""
        if not self._initialized:
            logger.warning("Symbols cache not initialized, returning empty list")
            return []
        return self.symbols[:limit]
    
    def validate_symbols(self, symbols: List[str]) -> List[str]:
        """Проверка символов против кеша"""
        if not self._initialized:
            return symbols  # Возвращаем как есть если кеш не инициализирован
        
        valid_symbols = set(self.symbols)
        return [s for s in symbols if s in valid_symbols]
    
    def get_stats(self) -> dict:
        """Статистика кеша"""
        return {
            'initialized': self._initialized,
            'total_symbols': len(self.symbols),
            'loaded_at': self.loaded_at.isoformat() if self.loaded_at else None
        }


# Singleton instance
symbols_cache = SymbolsCache()