import asyncio
import logging
from typing import Optional, Dict, Any, Set, List, Tuple
from datetime import datetime
from collections import defaultdict

from services.etherscan.service import etherscan_service
from cache.memory import cache
from config.settings import config

logger = logging.getLogger(__name__)


class GasAlertService:
    """Сервис мониторинга цены газа с оптимизированными пресетами"""
    
    def __init__(self):
        self.running = False
        self.monitor_task = None
        
        # Текущая и предыдущая цена газа
        self.current_gas_price: Optional[float] = None
        self.previous_gas_price: Optional[float] = None
        self.last_check_time: Optional[datetime] = None
        
        # Оптимизированная структура пресетов: threshold -> set(user_ids)
        self.presets_by_threshold: Dict[float, Set[int]] = defaultdict(set)
        
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
        
        # Загружаем пресеты из кеша
        await self._load_presets_from_cache()
        
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
    
    async def _load_presets_from_cache(self):
        """Загрузка пресетов из кеша в оптимизированную структуру"""
        gas_alerts = await cache.get_all_gas_alerts()
        
        for user_id, threshold in gas_alerts:
            self.presets_by_threshold[threshold].add(user_id)
        
        logger.info(f"Loaded {len(gas_alerts)} gas presets grouped by {len(self.presets_by_threshold)} thresholds")
    
    async def add_preset(self, user_id: int, threshold: float):
        """Добавление пресета"""
        # Удаляем старый пресет если есть
        await self.remove_preset(user_id)
        
        # Добавляем новый
        self.presets_by_threshold[threshold].add(user_id)
        
        logger.info(f"Added gas preset for user {user_id}: {threshold} Gwei")
    
    async def remove_preset(self, user_id: int):
        """Удаление пресета пользователя"""
        # Ищем пользователя во всех порогах
        for threshold, users in list(self.presets_by_threshold.items()):
            if user_id in users:
                users.remove(user_id)
                # Удаляем пустые пороги
                if not users:
                    del self.presets_by_threshold[threshold]
                break
        
        logger.info(f"Removed gas preset for user {user_id}")
    
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
                await self._check_crossings_optimized()
            
        except Exception as e:
            logger.error(f"Error checking gas price: {e}")
            self.stats['api_errors'] += 1
    
    async def _check_crossings_optimized(self):
        """Оптимизированная проверка пересечений O(k) где k - пороги в диапазоне"""
        if self.current_gas_price is None or self.previous_gas_price is None:
            return
        
        if not self.presets_by_threshold:
            return
        
        # Определяем диапазон изменения цены
        min_price = min(self.previous_gas_price, self.current_gas_price)
        max_price = max(self.previous_gas_price, self.current_gas_price)
        
        # Если цена не изменилась, пересечений нет
        if min_price == max_price:
            return
        
        alerts_to_send: List[Tuple[int, str]] = []
        users_to_remove = []
        
        # Проверяем только пороги в диапазоне изменения цены
        for threshold, user_ids in self.presets_by_threshold.items():
            # Порог пересечен если он находится между старой и новой ценой
            if min_price < threshold < max_price:
                logger.info(f"Gas price crossed threshold {threshold} Gwei: {self.previous_gas_price} → {self.current_gas_price}")
                
                # Определяем направление
                direction = "📈" if self.current_gas_price > threshold else "📉"
                
                # Создаем алерты для всех пользователей с этим порогом
                for user_id in user_ids.copy():  # copy() чтобы избежать изменения во время итерации
                    # ФОРМАТИРУЕМ алерт здесь
                    alert_text = (
                        f"{direction} <b>Газ алерт!</b>\n\n"
                        f"Цена газа пересекла ваш порог:\n"
                        f"🎯 Порог: {threshold} Gwei\n"
                        f"📍 Текущая цена: {self.current_gas_price} Gwei\n"
                        f"📊 Изменение: {self.previous_gas_price} → {self.current_gas_price} Gwei"
                    )
                    
                    alerts_to_send.append((user_id, alert_text))
                    users_to_remove.append(user_id)
                    
                    self.stats['crossings_detected'] += 1
        
        # Отправляем алерты через очередь
        if alerts_to_send:
            from utils.queue import message_queue
            await message_queue.add_alerts_bulk(alerts_to_send)
            
            self.stats['alerts_sent'] += len(alerts_to_send)
            logger.info(f"Sent {len(alerts_to_send)} gas crossing alerts")
        
        # Удаляем сработавшие пресеты ПОЛНОСТЬЮ из всех мест
        for user_id in users_to_remove:
            # Удаляем из БД
            from models.database import db_manager
            await db_manager.delete_gas_alert(user_id)
            
            # Удаляем из кеша
            await cache.remove_gas_alert(user_id)
            
            # Удаляем из сервиса
            await self.remove_preset(user_id)
    
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
            'total_presets': sum(len(users) for users in self.presets_by_threshold.values()),
            'unique_thresholds': len(self.presets_by_threshold),
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