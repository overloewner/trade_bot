import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from services.etherscan.service import etherscan_service
from cache.memory import cache
from utils.queue import message_queue, Priority
from config.settings import config

logger = logging.getLogger(__name__)


class GasAlertService:
    """Сервис мониторинга цены газа с триггерами пересечения"""
    
    def __init__(self):
        self.running = False
        self.monitor_task = None
        
        # Текущая цена газа
        self.current_gas_price: Optional[float] = None
        self.last_check_time: Optional[datetime] = None
        
        # Предыдущая цена для отслеживания пересечений
        self.previous_gas_price: Optional[float] = None
        
        # Статистика
        self.stats = {
            'checks_performed': 0,
            'alerts_sent': 0,
            'api_errors': 0,
            'crossings_detected': 0
        }
    
    async def start(self):
        """Запуск сервиса"""
        if self.running:
            return
        
        logger.info("Starting Gas Alert Service...")
        
        # Инициализируем Etherscan сервис
        await etherscan_service.initialize()
        
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
        
        await etherscan_service.close()
        logger.info("Gas Alert Service stopped")
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self.running:
            try:
                await self._check_gas_price()
                await asyncio.sleep(config.GAS_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in gas monitor loop: {e}")
                await asyncio.sleep(config.GAS_CHECK_INTERVAL)
    
    async def _check_gas_price(self):
        """Проверка цены газа и поиск пересечений"""
        try:
            # Получаем текущую цену
            new_price = await etherscan_service.get_gas_price()
            
            if new_price is None:
                self.stats['api_errors'] += 1
                return
            
            # Сохраняем предыдущую цену
            self.previous_gas_price = self.current_gas_price
            self.current_gas_price = new_price
            self.last_check_time = datetime.now()
            self.stats['checks_performed'] += 1
            
            logger.debug(f"Gas price updated: {new_price} Gwei")
            
            # Проверяем пересечения только если есть предыдущая цена
            if self.previous_gas_price is not None:
                await self._check_crossings()
            
        except Exception as e:
            logger.error(f"Error checking gas price: {e}")
            self.stats['api_errors'] += 1
    
    async def _check_crossings(self):
        """Проверка пересечений установленных порогов"""
        if self.current_gas_price is None or self.previous_gas_price is None:
            return
        
        # Получаем активные алерты
        gas_alerts = await cache.get_all_gas_alerts()
        
        if not gas_alerts:
            return
        
        alerts_to_send = []
        alerts_to_remove = []
        
        for user_id, threshold in gas_alerts:
            # Проверяем пересечение: цена "перешагнула" через порог
            crossed = self._price_crossed_threshold(
                self.previous_gas_price,
                self.current_gas_price,
                threshold
            )
            
            if crossed:
                logger.info(f"Gas price crossed threshold for user {user_id}: {threshold} Gwei")
                
                # Определяем направление
                direction = "📈" if self.current_gas_price > threshold else "📉"
                
                alert_text = (
                    f"{direction} <b>Газ алерт!</b>\n\n"
                    f"Цена газа пересекла ваш порог:\n"
                    f"🎯 Порог: {threshold} Gwei\n"
                    f"📍 Текущая цена: {self.current_gas_price} Gwei\n"
                    f"📊 Изменение: {self.previous_gas_price} → {self.current_gas_price} Gwei"
                )
                
                alerts_to_send.append((user_id, alert_text))
                alerts_to_remove.append(user_id)
                
                self.stats['crossings_detected'] += 1
        
        # Отправляем алерты
        if alerts_to_send:
            for user_id, text in alerts_to_send:
                await message_queue.add_message(
                    user_id=user_id,
                    content=text,
                    priority=Priority.HIGH
                )
            
            self.stats['alerts_sent'] += len(alerts_to_send)
            logger.info(f"Sent {len(alerts_to_send)} gas crossing alerts")
        
        # Удаляем сработавшие алерты
        for user_id in alerts_to_remove:
            await cache.remove_gas_alert(user_id)
            logger.info(f"Removed triggered gas alert for user {user_id}")
    
    def _price_crossed_threshold(self, prev_price: float, curr_price: float, threshold: float) -> bool:
        """Проверка пересечения порога ценой"""
        # Цена пересекла порог если:
        # 1. Была ниже порога, стала выше: prev < threshold <= curr
        # 2. Была выше порога, стала ниже: prev > threshold >= curr
        
        crossed_up = prev_price < threshold <= curr_price
        crossed_down = prev_price > threshold >= curr_price
        
        return crossed_up or crossed_down
    
    def get_current_gas_price(self) -> Optional[float]:
        """Получение текущей цены газа из памяти"""
        return self.current_gas_price
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики сервиса"""
        etherscan_stats = etherscan_service.get_stats()
        
        return {
            **self.stats,
            'running': self.running,
            'current_gas_price': self.current_gas_price,
            'previous_gas_price': self.previous_gas_price,
            'last_check_time': self.last_check_time.isoformat() if self.last_check_time else None,
            'etherscan_stats': etherscan_stats
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        is_healthy = True
        issues = []
        
        # Проверяем что сервис запущен
        if not self.running:
            is_healthy = False
            issues.append("Service not running")
        
        # Проверяем давность последней проверки
        if self.last_check_time:
            age = (datetime.now() - self.last_check_time).total_seconds()
            if age > config.GAS_CHECK_INTERVAL * 2:
                is_healthy = False
                issues.append(f"Last check too old: {age:.0f}s ago")
        else:
            is_healthy = False
            issues.append("No checks performed yet")
        
        # Проверяем наличие текущей цены
        if self.current_gas_price is None:
            is_healthy = False
            issues.append("No current gas price available")
        
        # Проверяем процент ошибок API
        if self.stats['checks_performed'] > 0:
            error_rate = self.stats['api_errors'] / self.stats['checks_performed']
            if error_rate > config.MAX_ERROR_RATE:
                is_healthy = False
                issues.append(f"High API error rate: {error_rate:.2%}")
        
        return {
            'healthy': is_healthy,
            'issues': issues,
            'last_check_age': (datetime.now() - self.last_check_time).total_seconds() if self.last_check_time else None
        }


# Singleton instance
gas_alert_service = GasAlertService()