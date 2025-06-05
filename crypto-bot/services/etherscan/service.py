import asyncio
import aiohttp
import logging
from typing import Optional
from datetime import datetime

from config.settings import config
from utils.rate_limiter import etherscan_limiter

logger = logging.getLogger(__name__)


class EtherscanService:
    """Сервис для работы с Etherscan API"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False
        
        # Статистика
        self.stats = {
            'requests_made': 0,
            'errors': 0,
            'last_request_time': None,
            'last_error': None
        }
    
    async def initialize(self):
        """Инициализация сервиса"""
        if self._initialized:
            return
        
        self.session = aiohttp.ClientSession()
        self._initialized = True
        logger.info("Etherscan service initialized")
    
    async def close(self):
        """Закрытие сервиса"""
        if self.session:
            await self.session.close()
            self._initialized = False
        logger.info("Etherscan service closed")
    
    async def get_gas_price(self) -> Optional[float]:
        """Получение текущей цены газа в Gwei"""
        if not self._initialized:
            await self.initialize()
        
        try:
            # Rate limiting
            await etherscan_limiter.acquire()
            
            params = {
                'module': 'gastracker',
                'action': 'gasoracle',
                'apikey': config.ETHERSCAN_API_KEY
            }
            
            async with self.session.get(
                config.ETHERSCAN_API_URL,
                params=params,
                timeout=config.HTTP_REQUEST_TIMEOUT
            ) as response:
                
                self.stats['requests_made'] += 1
                self.stats['last_request_time'] = datetime.now()
                
                if response.status != 200:
                    logger.error(f"Etherscan API HTTP error: {response.status}")
                    self.stats['errors'] += 1
                    return None
                
                data = await response.json()
                
                if data.get('status') != '1':
                    error_msg = data.get('message', 'Unknown error')
                    logger.error(f"Etherscan API error: {error_msg}")
                    self.stats['errors'] += 1
                    self.stats['last_error'] = error_msg
                    return None
                
                # Берем SafeGasPrice
                result = data.get('result', {})
                gas_price = float(result.get('SafeGasPrice', 0))
                
                if gas_price <= 0:
                    logger.warning("Received invalid gas price from API")
                    return None
                
                logger.debug(f"Retrieved gas price: {gas_price} Gwei")
                return gas_price
                
        except asyncio.TimeoutError:
            logger.error("Etherscan API request timeout")
            self.stats['errors'] += 1
            self.stats['last_error'] = "Request timeout"
            return None
        except Exception as e:
            logger.error(f"Error fetching gas price: {e}")
            self.stats['errors'] += 1
            self.stats['last_error'] = str(e)
            return None
    
    def get_stats(self) -> dict:
        """Получение статистики сервиса"""
        return {
            **self.stats,
            'initialized': self._initialized,
            'error_rate': self.stats['errors'] / max(self.stats['requests_made'], 1)
        }


# Singleton instance
etherscan_service = EtherscanService()