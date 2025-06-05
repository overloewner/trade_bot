from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import logging
from contextlib import asynccontextmanager

from config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class PresetData:
    """Данные пресета в памяти"""
    id: int
    user_id: int
    name: str
    pairs: List[str]
    intervals: List[str]
    percent_change: float
    is_active: bool = True


@dataclass
class AlertRecord:
    """Запись об отправленном алерте для дедупликации"""
    user_id: int
    symbol: str
    interval: str
    timestamp: datetime
    percent_change: float


class MemoryCache:
    """Централизованный in-memory кеш для всех данных"""
    
    def __init__(self):
        # FSM состояния пользователей
        self.user_states: Dict[int, Dict[str, Any]] = {}
        
        # Активные пресеты: symbol -> interval -> user_id -> preset_ids
        self.active_subscriptions: Dict[str, Dict[str, Dict[int, List[int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        
        # Все пресеты для быстрого доступа
        self.presets: Dict[int, PresetData] = {}
        
        # Газовые алерты: user_id -> threshold_gwei
        self.gas_alerts: Dict[int, float] = {}
        
        # История алертов для дедупликации
        self.alert_history: deque = deque(maxlen=config.ALERT_HISTORY_SIZE)
        
        # Блокировки для потокобезопасности
        self._locks = {
            'subscriptions': asyncio.Lock(),
            'presets': asyncio.Lock(),
            'gas_alerts': asyncio.Lock(),
            'alerts': asyncio.Lock(),
            'states': asyncio.Lock()
        }
        
        # Статистика
        self.stats = {
            'alerts_sent': 0,
            'alerts_deduplicated': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    @asynccontextmanager
    async def _lock(self, name: str):
        """Контекстный менеджер для блокировок"""
        async with self._locks[name]:
            yield
    
    async def load_from_db(self, db_manager) -> None:
        """Загрузка данных из БД при старте"""
        logger.info("Loading data from database to cache...")
        
        # Загружаем активные пресеты
        presets = await db_manager.get_all_active_presets()
        async with self._lock('presets'):
            for preset_data in presets:
                preset = PresetData(
                    id=preset_data['id'],
                    user_id=preset_data['user_id'],
                    name=preset_data['name'],
                    pairs=preset_data['pairs'],
                    intervals=preset_data['intervals'],
                    percent_change=float(preset_data['percent_change']),
                    is_active=preset_data['is_active']
                )
                self.presets[preset.id] = preset
                
                # Добавляем в активные подписки ТОЛЬКО если активен
                if preset.is_active:
                    await self._add_preset_to_subscriptions(preset)
                    logger.info(f"Loaded active preset {preset.id} with {len(preset.pairs)} pairs and {len(preset.intervals)} intervals")
        
        # Загружаем газовые алерты
        gas_alerts = await db_manager.get_all_gas_alerts()
        async with self._lock('gas_alerts'):
            for alert in gas_alerts:
                self.gas_alerts[alert['user_id']] = float(alert['threshold_gwei'])
        
        logger.info(f"Loaded {len(self.presets)} presets and {len(self.gas_alerts)} gas alerts")
        
        # Логируем общую статистику подписок
        total_subs = 0
        for symbol_data in self.active_subscriptions.values():
            for interval_data in symbol_data.values():
                total_subs += len(interval_data)
        logger.info(f"Total active subscriptions: {total_subs}")
    
    async def _add_preset_to_subscriptions(self, preset: PresetData) -> None:
        """Добавление пресета в подписки (без блокировки)"""
        for symbol in preset.pairs:
            for interval in preset.intervals:
                self.active_subscriptions[symbol][interval][preset.user_id].append(preset.id)
                logger.debug(f"Added subscription: {symbol}@{interval} for user {preset.user_id}")
    
    async def _remove_preset_from_subscriptions(self, preset: PresetData) -> None:
        """Удаление пресета из подписок (без блокировки)"""
        for symbol in preset.pairs:
            for interval in preset.intervals:
                user_presets = self.active_subscriptions[symbol][interval].get(preset.user_id, [])
                if preset.id in user_presets:
                    user_presets.remove(preset.id)
                
                # Удаляем пустые записи
                if not user_presets:
                    self.active_subscriptions[symbol][interval].pop(preset.user_id, None)
                if not self.active_subscriptions[symbol][interval]:
                    self.active_subscriptions[symbol].pop(interval, None)
                if not self.active_subscriptions[symbol]:
                    self.active_subscriptions.pop(symbol, None)
    
    # Управление пресетами
    async def add_preset(self, preset: PresetData) -> None:
        """Добавление пресета в кеш"""
        async with self._lock('presets'):
            self.presets[preset.id] = preset
            
            if preset.is_active:
                await self._add_preset_to_subscriptions(preset)
                logger.info(f"Added active preset {preset.id} to subscriptions")
    
    async def remove_preset(self, preset_id: int) -> None:
        """Удаление пресета из кеша"""
        async with self._lock('presets'):
            preset = self.presets.get(preset_id)
            if not preset:
                return
            
            # Удаляем из активных подписок
            await self._remove_preset_from_subscriptions(preset)
            
            # Удаляем сам пресет
            del self.presets[preset_id]
            logger.info(f"Removed preset {preset_id} from cache")
    
    async def update_preset_status(self, preset_id: int, is_active: bool) -> None:
        """Обновление статуса пресета"""
        async with self._lock('presets'):
            preset = self.presets.get(preset_id)
            if not preset:
                return
            
            if preset.is_active == is_active:
                return
            
            preset.is_active = is_active
            
            if is_active:
                # Добавляем в активные подписки
                await self._add_preset_to_subscriptions(preset)
                logger.info(f"Activated preset {preset_id}")
            else:
                # Удаляем из активных подписок
                await self._remove_preset_from_subscriptions(preset)
                logger.info(f"Deactivated preset {preset_id}")
    
    async def get_subscribed_users(self, symbol: str, interval: str) -> Dict[int, List[PresetData]]:
        """Получение пользователей, подписанных на symbol/interval"""
        async with self._lock('subscriptions'):
            result = {}
            user_preset_ids = self.active_subscriptions.get(symbol, {}).get(interval, {})
            
            logger.debug(f"Checking subscriptions for {symbol}@{interval}: {len(user_preset_ids)} users")
            
            for user_id, preset_ids in user_preset_ids.items():
                user_presets = []
                for preset_id in preset_ids:
                    preset = self.presets.get(preset_id)
                    if preset and preset.is_active:
                        user_presets.append(preset)
                
                if user_presets:
                    result[user_id] = user_presets
                    logger.debug(f"User {user_id} has {len(user_presets)} active presets for {symbol}@{interval}")
            
            self.stats['cache_hits'] += 1
            return result
    
    # Управление газовыми алертами
    async def set_gas_alert(self, user_id: int, threshold_gwei: float) -> None:
        """Установка газового алерта"""
        async with self._lock('gas_alerts'):
            self.gas_alerts[user_id] = threshold_gwei
    
    async def remove_gas_alert(self, user_id: int) -> None:
        """Удаление газового алерта"""
        async with self._lock('gas_alerts'):
            self.gas_alerts.pop(user_id, None)
    
    async def get_all_gas_alerts(self) -> List[Tuple[int, float]]:
        """Получение всех активных газовых алертов"""
        async with self._lock('gas_alerts'):
            return list(self.gas_alerts.items())
    
    # Дедупликация алертов - УБРАНА
    async def record_alert(self, alert: AlertRecord) -> None:
        """Запись отправленного алерта"""
        async with self._lock('alerts'):
            self.alert_history.append(alert)
            self.stats['alerts_sent'] += 1
    
    # FSM состояния
    async def set_user_state(self, user_id: int, state: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Установка состояния пользователя"""
        async with self._lock('states'):
            self.user_states[user_id] = {
                'state': state,
                'data': data or {},
                'timestamp': datetime.now()
            }
    
    async def get_user_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение состояния пользователя"""
        async with self._lock('states'):
            return self.user_states.get(user_id)
    
    async def clear_user_state(self, user_id: int) -> None:
        """Очистка состояния пользователя"""
        async with self._lock('states'):
            self.user_states.pop(user_id, None)
    
    # Статистика
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кеша"""
        total_subscriptions = 0
        for symbol_data in self.active_subscriptions.values():
            for interval_data in symbol_data.values():
                total_subscriptions += len(interval_data)
        
        return {
            **self.stats,
            'total_presets': len(self.presets),
            'active_presets': sum(1 for p in self.presets.values() if p.is_active),
            'total_gas_alerts': len(self.gas_alerts),
            'unique_symbols': len(self.active_subscriptions),
            'total_subscriptions': total_subscriptions,
            'alert_history_size': len(self.alert_history)
        }
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Статистика для конкретного пользователя"""
        async with self._lock('presets'):
            user_presets = [p for p in self.presets.values() if p.user_id == user_id]
            active_presets = [p for p in user_presets if p.is_active]
            
            return {
                'total_presets': len(user_presets),
                'active_presets': len(active_presets),
                'has_gas_alert': user_id in self.gas_alerts,
                'gas_threshold': self.gas_alerts.get(user_id)
            }


# Singleton instance
cache = MemoryCache()