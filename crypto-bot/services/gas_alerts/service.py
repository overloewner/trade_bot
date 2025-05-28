import asyncio
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
from collections import deque
import aiohttp

from cache.memory import cache
from utils.queue import message_queue, Priority
from utils.rate_limiter import etherscan_limiter
from config.settings import config

logger = logging.getLogger(__name__)


class GasAlertService:
    """Сервис мониторинга цены газа Ethereum"""
    
    def __init__(self):
        self.running = False
        self.monitor_task = None
        
        # История цен газа (timestamp, price_gwei)
        self.gas_history: deque = deque(maxlen=config.GAS_HISTORY_SIZE)
        
        # Последняя известная цена
        self.last_gas_price: Optional[float] = None
        self.last_check_time: Optional[datetime] = None
        
        # Кеш уведомленных пользователей (чтобы не спамить)
        self.notified_users: Dict[int, datetime] = {}
        self.notification_cooldown = 3600  # 1 час между уведомлениями
        
        # Статистика
        self.stats = {
            'checks_performed': 0,
            'alerts_sent': 0,
            'api_errors': 0,
            'last_error': None
        }
    
    async def start(self):
        """Запуск сервиса"""
        if self.running:
            return
        
        logger.info("Starting Gas Alert Service...")
        
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Gas Alert Service started")
    
    async def stop(self):
        """Остановка сервиса"""
        logger.info("Stopping Gas Alert Service...")
        
        self.running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Gas Alert Service stopped")
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self.running:
            try:
                # Проверяем цену газа
                await self._check_gas_price()
                
                # Ждем до следующей проверки
                await asyncio.sleep(config.GAS_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in gas monitor loop: {e}")
                self.stats['last_error'] = str(e)
                await asyncio.sleep(config.GAS_CHECK_INTERVAL)
    
    async def _check_gas_price(self):
        """Проверка текущей цены газа"""
        try:
            # Rate limiting
            await etherscan_limiter.acquire()
            
            # Получаем цену газа
            gas_price = await self._fetch_gas_price()
            
            if gas_price is None:
                return
            
            # Сохраняем в истории
            self.gas_history.append({
                'timestamp': datetime.now(),
                'price': gas_price
            })
            
            self.last_gas_price = gas_price
            self.last_check_time = datetime.now()
            
            # Обновляем статистику
            self.stats['checks_performed'] += 1
            
            # Проверяем алерты
            await self._check_alerts(gas_price)
            
            logger.debug(f"Gas price: {gas_price} Gwei")
            
        except Exception as e:
            logger.error(f"Error checking gas price: {e}")
            self.stats['api_errors'] += 1
            raise
    
    async def _fetch_gas_price(self) -> Optional[float]:
        """Получение цены газа с Etherscan API"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'module': 'gastracker',
                    'action': 'gasoracle',
                    'apikey': config.ETHERSCAN_API_KEY
                }
                
                async with session.get(
                    config.ETHERSCAN_API_URL,
                    params=params,
                    timeout=10
                ) as response:
                    if response.status != 200:
                        logger.error(f"Etherscan API error: {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get('status') != '1':
                        logger.error(f"Etherscan API error: {data.get('message')}")
                        return None
                    
                    # Берем SafeGasPrice
                    result = data.get('result', {})
                    gas_price = float(result.get('SafeGasPrice', 0))
                    
                    return gas_price
                    
        except Exception as e:
            logger.error(f"Error fetching gas price: {e}")
            return None
    
    async def _check_alerts(self, current_price: float):
        """Проверка и отправка алертов"""
        # Получаем пользователей с порогом >= текущей цены
        users_to_alert = await cache.get_gas_alerts_below(current_price)
        
        if not users_to_alert:
            return
        
        # Фильтруем пользователей по cooldown
        now = datetime.now()
        alerts_to_send = []
        
        for user_id, threshold in users_to_alert:
            # Проверяем cooldown
            last_notified = self.notified_users.get(user_id)
            if last_notified and (now - last_notified).seconds < self.notification_cooldown:
                continue
            
            # Формируем алерт
            alert_text = (
                f"⛽ <b>Газ алерт!</b>\n\n"
                f"Цена газа опустилась ниже вашего порога:\n"
                f"📍 Текущая цена: {current_price} Gwei\n"
                f"🎯 Ваш порог: {threshold} Gwei\n\n"
                f"Самое время для транзакций!"
            )
            
            alerts_to_send.append((user_id, alert_text))
            self.notified_users[user_id] = now
        
        # Отправляем алерты
        if alerts_to_send:
            for user_id, text in alerts_to_send:
                await message_queue.add_message(
                    user_id=user_id,
                    content=text,
                    priority=Priority.HIGH
                )
            
            self.stats['alerts_sent'] += len(alerts_to_send)
            logger.info(f"Sent {len(alerts_to_send)} gas alerts")
    
    def get_gas_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Получение истории цен газа"""
        if not self.gas_history:
            return []
        
        # Фильтруем по времени
        cutoff = datetime.now() - timedelta(hours=hours)
        filtered = [
            item for item in self.gas_history
            if item['timestamp'] > cutoff
        ]
        
        return filtered
    
    def get_current_gas_price(self) -> Optional[float]:
        """Получение текущей цены газа"""
        return self.last_gas_price
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики сервиса"""
        return {
            **self.stats,
            'running': self.running,
            'last_gas_price': self.last_gas_price,
            'last_check_time': self.last_check_time.isoformat() if self.last_check_time else None,
            'history_size': len(self.gas_history),
            'active_alerts': len(cache.gas_alerts) if hasattr(cache, 'gas_alerts') else 0
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        is_healthy = True
        issues = []
        
        # Проверяем, что сервис запущен
        if not self.running:
            is_healthy = False
            issues.append("Service not running")
        
        # Проверяем давность последней проверки
        if self.last_check_time:
            age = (datetime.now() - self.last_check_time).seconds
            if age > config.GAS_CHECK_INTERVAL * 2:
                is_healthy = False
                issues.append(f"Last check too old: {age}s ago")
        else:
            is_healthy = False
            issues.append("No checks performed yet")
        
        # Проверяем количество ошибок
        error_rate = self.stats['api_errors'] / max(self.stats['checks_performed'], 1)
        if error_rate > 0.5:
            is_healthy = False
            issues.append(f"High error rate: {error_rate:.2%}")
        
        return {
            'healthy': is_healthy,
            'issues': issues,
            'last_check_age': (datetime.now() - self.last_check_time).seconds if self.last_check_time else None,
            'error_rate': error_rate
        }
    
    def clear_notification_cooldown(self, user_id: int):
        """Очистка cooldown для пользователя (для тестирования)"""
        self.notified_users.pop(user_id, None)


# Singleton instance
gas_alert_service = GasAlertService()