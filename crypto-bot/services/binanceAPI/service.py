import aiohttp
import logging
from typing import List, Optional
from datetime import datetime, timedelta
import asyncio

from config.settings import config

logger = logging.getLogger(__name__)


class BinanceAPIClient:
    """Клиент для работы с API Binance Futures - только запросы к API"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False
        
    async def initialize(self):
        """Инициализация клиента"""
        if self._initialized:
            return
            
        self.session = aiohttp.ClientSession()
        self._initialized = True
        
    async def close(self):
        """Закрытие клиента"""
        if self.session:
            await self.session.close()
            self._initialized = False
            
    async def fetch_all_futures_symbols(self) -> List[str]:
        """Получение всех активных USDT фьючерсных пар с Binance"""
        if not self._initialized:
            await self.initialize()
            
        try:
            if not self.session:
                return []
                
            # Используем exchangeInfo для получения только торгуемых пар
            url = f"{config.BINANCE_REST_URL}/fapi/v1/exchangeInfo"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch exchange info. Status: {response.status}")
                    return []
                    
                data = await response.json()
                
                # Извлекаем только активные USDT пары
                symbols = []
                for symbol_info in data.get('symbols', []):
                    symbol = symbol_info.get('symbol', '')
                    status = symbol_info.get('status', '')
                    
                    # Только активные USDT пары
                    if (symbol.endswith('USDT') and 
                        status == 'TRADING' and
                        symbol_info.get('contractType') == 'PERPETUAL'):
                        symbols.append(symbol)
                
                logger.info(f"Fetched {len(symbols)} active perpetual USDT futures symbols from API")
                return symbols
                
        except Exception as e:
            logger.error(f"Error fetching symbols from Binance: {e}")
            return []
            
    async def fetch_top_symbols_by_volume(self, limit: int = 100) -> List[str]:
        """Получение топ символов по объему"""
        if not self._initialized:
            await self.initialize()
            
        try:
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
            return []


# Singleton instance
binance_api = BinanceAPIClient()