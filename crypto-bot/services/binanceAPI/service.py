# api/binance_api.py
import aiohttp
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

from config.settings import config

logger = logging.getLogger(__name__)


class BinanceAPIClient:
    """Клиент для работы с API Binance Futures"""
    
    def __init__(self):
        self.symbols_cache: List[str] = []
        self.last_update: Optional[datetime] = None
        self.cache_lock = asyncio.Lock()
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False
        
    async def initialize(self):
        """Инициализация клиента"""
        if self._initialized:
            return
            
        self.session = aiohttp.ClientSession()
        await self._update_symbols_cache()
        self._initialized = True
        
    async def close(self):
        """Закрытие клиента"""
        if self.session:
            await self.session.close()
            self._initialized = False
            
    async def _update_symbols_cache(self):
        """Обновление кеша символов"""
        async with self.cache_lock:
            try:
                symbols = await self._fetch_all_futures_symbols()
                if symbols:
                    self.symbols_cache = symbols
                    self.last_update = datetime.now()
                    logger.info(f"Updated symbols cache. Total symbols: {len(symbols)}")
                else:
                    # Если не удалось получить символы, используем базовые
                    if not self.symbols_cache:
                        self.symbols_cache = [
                            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT',
                            'SOLUSDT', 'DOTUSDT', 'DOGEUSDT', 'AVAXUSDT', 'MATICUSDT'
                        ]
                        logger.warning("Using fallback symbols list")
            except Exception as e:
                logger.error(f"Failed to update symbols cache: {e}")
                if not self.symbols_cache:
                    # Устанавливаем минимальный набор для работы
                    self.symbols_cache = ['BTCUSDT', 'ETHUSDT']
                    logger.warning("Using minimal symbols list")
                    
    async def _fetch_all_futures_symbols(self) -> List[str]:
        """Получение всех активных USDT фьючерсных пар с Binance"""
        try:
            if not self.session:
                return []
                
            # Используем ticker endpoint - он возвращает только активные пары
            url = f"{config.BINANCE_REST_URL}/fapi/v1/ticker/24hr"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch active symbols. Status: {response.status}")
                    return []
                    
                data = await response.json()
                
                # Извлекаем только USDT пары - если они в ticker, значит активны
                symbols = [
                    item['symbol'] for item in data 
                    if item['symbol'].endswith('USDT')
                ]
                
                logger.info(f"Found {len(symbols)} active USDT futures symbols")
                return symbols
                
        except Exception as e:
            logger.error(f"Error fetching active symbols from Binance: {e}")
            return []
                
        except Exception as e:
            logger.error(f"Error fetching symbols from Binance: {e}")
            return []
            
    async def get_all_symbols(self, force_update: bool = False) -> List[str]:
        """Получение всех доступных символов"""
        # Проверяем инициализацию
        if not self._initialized:
            await self.initialize()
            
        async with self.cache_lock:
            # Обновляем кеш если он пустой или устарел (старше 1 часа)
            if (not self.symbols_cache or 
                force_update or 
                (self.last_update and 
                 (datetime.now() - self.last_update) > timedelta(hours=1))):
                await self._update_symbols_cache()
                
            return self.symbols_cache.copy()
            
    async def get_top_symbols_by_volume(self, limit: int = 100) -> List[str]:
        """Получение топ символов по объему"""
        try:
            if not self._initialized:
                await self.initialize()
                
            if not self.session:
                return []
                
            url = f"{config.BINANCE_REST_URL}/fapi/v1/ticker/24hr"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch tickers. Status: {response.status}")
                    return []
                    
                data = await response.json()
                usdt_pairs = [
                    item for item in data
                    if item['symbol'].endswith('USDT')
                ]
                
                # Сортируем по объему (quoteVolume)
                usdt_pairs.sort(
                    key=lambda x: float(x['quoteVolume']),
                    reverse=True
                )
                
                return [pair['symbol'] for pair in usdt_pairs[:limit]]
                
        except Exception as e:
            logger.error(f"Error fetching top symbols: {e}")
            # Возвращаем кешированные символы как fallback
            return self.symbols_cache[:limit] if self.symbols_cache else []


# Singleton instance
binance_api = BinanceAPIClient()